"""從系統匯出的處方紀錄 Excel 讀取並統計資料

Excel 格式（單一 sheet「處方紀錄」）：
欄位：流水號 | 姓名 | 性別 | 生日 | 身分證字號 | 手機 | 處方類型 |
      開立診所 | 開立醫師 | 是否選課 | 選課名稱 | 選課時段 |
      執行單位 | 執行人員 | 執行處方 | 執行課程 | 執行日期 |
      處方費 | 處方執行費 | 處方處置費 | 已核銷 | 開立日期時間

雙檔案模式：
  - 開立處方紀錄 Excel：用於計算處方費 + 健康管理費
  - 執行處方紀錄 Excel：用於計算處方執行費 + 處方處置費

匯出端以「開立日期 = 申報月」篩 issuance Excel、以「執行日期 = 申報月」篩
execution Excel，即可正確處理「2 月開立 3 月執行」等跨月情境。
"""

import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import openpyxl

from models import AllData, DoctorPrescription, HealthManagement, ExecutorData, PatientRecord, ReceiptInfo
from config import FEE_PER_PRESCRIPTION, FEE_PER_EXECUTION
from treatment_fees import classify_course, fee_for_label

PRESCRIPTION_TYPES = {"運動處方", "營養處方", "情緒調適處方", "社會處方"}

# Column indices (0-based)
COL_NAME = 1
COL_GENDER = 2
COL_BIRTH = 3
COL_ID = 4
COL_PHONE = 5
COL_PTYPE = 6
COL_CLINIC = 7
COL_DOCTOR = 8
COL_EXEC_UNIT = 12
COL_EXEC_PERSON = 13
COL_EXEC_DONE = 14
COL_EXEC_COURSE = 15  # 執行課程（與執行單位一起決定處置費費率：PLUS2 200 / 線上 100 / 其餘 400）
COL_EXEC_DATE = 16
COL_PRESC_FEE = 17   # 處方費（每筆金額）
COL_EXEC_FEE = 18    # 處方執行費（每筆金額）
COL_DATE = 21


def _course_of(row) -> tuple:
    """取該筆紀錄的（執行課程, 執行單位）— 兩欄一起決定處置費費率。

    PLUS2 標在「執行課程」(如 PLUS2-0819富洲里-運動)，
    線上課程標在「執行單位」(= 線上微課程)，只看一欄會漏掉另一種。
    舊格式來源檔欄數可能不足，缺欄時回空字串 → 歸「一般課程」400 元。
    """
    course = str(row[COL_EXEC_COURSE] or "") if len(row) > COL_EXEC_COURSE else ""
    unit = str(row[COL_EXEC_UNIT] or "") if len(row) > COL_EXEC_UNIT else ""
    return course, unit


def _load_rows(filepath: str) -> list:
    """讀 Excel 的「處方紀錄」分頁，回傳 row 列表（每 row 是 tuple）。
    路徑為空或檔案不存在時回傳空列表。"""
    if not filepath or not os.path.isfile(filepath):
        return []
    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb["處方紀錄"]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        rows.append(row)
    wb.close()
    return rows


def read_prescription_report(issuance_path: str = "",
                             execution_path: str = "",
                             report_year: int = 115,
                             report_month: int = 4,
                             min_prescriptions: int = 0,
                             name_overrides: Optional[dict] = None,
                             issuance_rows: Optional[list] = None,
                             execution_rows: Optional[list] = None) -> AllData:
    """讀取處方紀錄並統計。

    - issuance_path: 開立處方紀錄 Excel（必要）— 計算處方費 + 健康管理費
    - execution_path: 執行處方紀錄 Excel（選填）— 計算處方執行費 + 處方處置費
                     若空，issuance_path 兼作執行紀錄（單檔舊行為）
    - name_overrides: {系統登入帳號: 真名} 對照表（來自共用檔「登入帳號」欄）。
                     來源系統偶爾把「開立醫師/執行人員」欄填成登入帳號（如
                     Koanclinic6、09062811AA），會讓同一人被拆成兩組。此對照
                     在分組前把帳號正規化成真名，避免拆分。
    """
    overrides = name_overrides or {}

    def _norm(val) -> str:
        """把系統登入帳號正規化成真名（對不到就原樣回傳）"""
        s = str(val or "")
        return overrides.get(s.strip(), s)

    # 資料來源：直接給 rows（backend_api 抓來的）優先，否則讀 Excel。
    # 兩者的 row 格式相同（backend_api.record_to_row 已對齊 Excel 22 欄順序），
    # 所以底下的統計邏輯不必分辨來源。
    if issuance_rows is not None or execution_rows is not None:
        issuance_records = list(issuance_rows or [])
        execution_records = list(execution_rows if execution_rows is not None
                                 else issuance_records)
    else:
        issuance_records = _load_rows(issuance_path)
        if execution_path and execution_path != issuance_path:
            execution_records = _load_rows(execution_path)
        else:
            execution_records = issuance_records

    # === 1. 從「開立處方紀錄」收集：處方費、健管費、醫師開立民眾 ===
    doctor_prescription: dict = defaultdict(lambda: defaultdict(int))
    doctor_presc_fee: dict = defaultdict(int)
    doctor_records_issuance: dict = defaultdict(list)
    clinic_records: dict = defaultdict(list)

    for row in issuance_records:
        ptype = str(row[COL_PTYPE] or "")
        clinic = str(row[COL_CLINIC] or "")
        doctor = _norm(row[COL_DOCTOR])  # 開立醫師：帳號→真名，避免拆組
        if ptype not in PRESCRIPTION_TYPES:
            continue

        doctor_prescription[(clinic, doctor)][ptype] += 1
        doctor_records_issuance[(clinic, doctor)].append(row)
        clinic_records[clinic].append(row)
        try:
            pf = int(row[COL_PRESC_FEE] or 0)
            doctor_presc_fee[(clinic, doctor)] += pf
        except (TypeError, ValueError):
            pass

    # === 2. 從「執行處方紀錄」收集：執行費、處置費、執行人員 ===
    doctor_execution: dict = defaultdict(lambda: defaultdict(int))
    doctor_exec_fee: dict = defaultdict(int)
    doctor_records_execution: dict = defaultdict(list)
    executor_records: dict = defaultdict(lambda: defaultdict(list))

    for row in execution_records:
        ptype = str(row[COL_PTYPE] or "")
        clinic = str(row[COL_CLINIC] or "")
        doctor = _norm(row[COL_DOCTOR])  # 開立醫師：帳號→真名，避免拆組
        if ptype not in PRESCRIPTION_TYPES:
            continue

        exec_date = row[COL_EXEC_DATE]
        exec_person = _norm(row[COL_EXEC_PERSON])  # 執行人員：帳號→真名
        exec_unit = row[COL_EXEC_UNIT]
        exec_done_flag = row[COL_EXEC_DONE]

        # 「已執行」判斷：優先看「執行日期」(Q 欄) 有無值；
        # 若 Excel 沒填日期，退回看 O 欄勾選+執行人員。
        # 這樣避免「執行人員事前指派」導致未執行也被誤算。
        if exec_date:
            executed = True
        else:
            executed = bool(exec_done_flag) and bool(exec_person)
        if not executed:
            continue

        doctor_execution[(clinic, doctor)][ptype] += 1
        doctor_records_execution[(clinic, doctor)].append(row)
        executor_records[(str(exec_unit or ""), str(exec_person or ""))][ptype].append(row)
        try:
            ef = int(row[COL_EXEC_FEE] or 0)
            doctor_exec_fee[(clinic, doctor)] += ef
        except (TypeError, ValueError):
            pass

    # === 3. 建立 DoctorPrescription 列表（issuance ∪ execution 的醫師）===
    PRESC_UNIT = FEE_PER_PRESCRIPTION
    EXEC_UNIT = FEE_PER_EXECUTION
    all_doctor_keys = set(doctor_prescription.keys()) | set(doctor_execution.keys())
    doctors = []
    for clinic, doctor_name in sorted(all_doctor_keys):
        type_counts = doctor_prescription.get((clinic, doctor_name), {})
        exec_counts = doctor_execution.get((clinic, doctor_name), {})
        total_presc = sum(type_counts.values())
        total_exec = sum(exec_counts.values())

        presc_fee = doctor_presc_fee.get((clinic, doctor_name), 0) or (total_presc * PRESC_UNIT)
        exec_fee = doctor_exec_fee.get((clinic, doctor_name), 0) or (total_exec * EXEC_UNIT)

        # 建立兩份民眾明細：
        #   patients → 開立的民眾（處方費明細用）
        #   execution_patients → 已執行的民眾（執行費明細用）
        def _build_patient_list(source_rows):
            out = []
            seen = set()
            for row in source_rows:
                ptype = str(row[COL_PTYPE] or "")
                key = (row[COL_NAME], row[COL_ID], ptype)
                if key in seen:
                    continue
                seen.add(key)
                # 開立日期時間可能是 datetime 物件，轉字串取日期部分
                issue_raw = row[COL_DATE] if len(row) > COL_DATE else ""
                if issue_raw:
                    issue_str = str(issue_raw).split(" ")[0]
                else:
                    issue_str = ""
                out.append(PatientRecord(
                    name=str(row[COL_NAME] or ""),
                    id_number=str(row[COL_ID] or ""),
                    birth_date=str(row[COL_BIRTH] or ""),
                    prescriber=doctor_name,
                    exec_date=str(row[COL_EXEC_DATE] or ""),
                    issue_date=issue_str,
                    prescription_type=ptype,
                ))
            return out

        patients_issuance = _build_patient_list(
            doctor_records_issuance.get((clinic, doctor_name), []))
        patients_execution = _build_patient_list(
            doctor_records_execution.get((clinic, doctor_name), []))

        doctors.append(DoctorPrescription(
            medical_institution=clinic,
            doctor_name=doctor_name,
            exercise=type_counts.get("運動處方", 0),
            nutrition=type_counts.get("營養處方", 0),
            emotion=type_counts.get("情緒調適處方", 0),
            social=type_counts.get("社會處方", 0),
            exercise_exec=exec_counts.get("運動處方", 0),
            nutrition_exec=exec_counts.get("營養處方", 0),
            emotion_exec=exec_counts.get("情緒調適處方", 0),
            social_exec=exec_counts.get("社會處方", 0),
            prescription_fee=presc_fee,
            execution_fee=exec_fee,
            patients=patients_issuance,
            execution_patients=patients_execution,
        ))

    # === 3. 健康管理費（按診所統計）===
    health_mgmts = []
    for clinic, rows in sorted(clinic_records.items()):
        unique_patients = set()
        admin_person = ""
        for row in rows:
            # 用 (姓名, 身分證) 識別不同民眾;只用姓名會把同名不同人併成一個
            unique_patients.add((row[COL_NAME], row[COL_ID]))
            # 診所人員(行政)留空,等 app.py 從個資檔反查;
            # 不再用「開立醫師」當佔位 — 個資檔無對應時會誤把醫師名印到明細表。

        total_count = len(rows)
        people_count = len(unique_patients)

        if min_prescriptions > 0 and total_count < min_prescriptions:
            continue

        # 此診所的民眾明細（去重：name+id+ptype）
        hm_patients = []
        seen = set()
        for row in rows:
            ptype = str(row[COL_PTYPE] or "")
            key = (row[COL_NAME], row[COL_ID], ptype)
            if key in seen:
                continue
            seen.add(key)
            # 開立日期時間可能是 datetime 物件，轉字串取日期部分
            issue_raw = row[COL_DATE] if len(row) > COL_DATE else ""
            if issue_raw:
                issue_str = str(issue_raw).split(" ")[0]
            else:
                issue_str = ""
            hm_patients.append(PatientRecord(
                name=str(row[COL_NAME] or ""),
                id_number=str(row[COL_ID] or ""),
                birth_date=str(row[COL_BIRTH] or ""),
                prescriber=_norm(row[COL_DOCTOR]),  # 處方人員：帳號→真名
                exec_date=str(row[COL_EXEC_DATE] or ""),
                issue_date=issue_str,
                prescription_type=ptype,
            ))

        health_mgmts.append(HealthManagement(
            medical_institution=clinic,
            clinic_person=admin_person,
            prescription_people=people_count,
            prescription_count=total_count,
            is_qualified=True,
            patients=hm_patients,
        ))

    # === 4. 執行人員端 ===
    # 同一位執行人員若兼任多種處方類型(例:運動處方 + 情緒調適處方),
    # 仍合成一筆 ExecutorData:領據用 4×6 pivot 表一次列出各類份數與金額,
    # 民眾明細表也合成一份,但依「運動 → 營養 → 情緒調適 → 社會」順序排列。
    executors = []
    PTYPE_ORDER = ["運動處方", "營養處方", "情緒調適處方", "社會處方"]
    PTYPE_INDEX = {p: i for i, p in enumerate(PTYPE_ORDER)}

    for (exec_unit, exec_person), type_records in sorted(executor_records.items()):
        type_counts = {pt: len(recs) for pt, recs in type_records.items() if recs}
        total_service = sum(type_counts.values())

        # 處置費費率分流:每筆執行紀錄依「執行課程」欄歸類
        #   一般課程 400 / 處方PLUS2 200 / 視訊課程 100(規則見 config.json)
        # course_counts = {費率標籤: {處方類型: 人次}};金額逐筆按各自單價累加,
        # 不再用「總人次 × 單一 400」。
        course_counts: dict = defaultdict(lambda: defaultdict(int))
        treatment_amount = 0
        for ptype, recs in type_records.items():
            for row in recs:
                label = classify_course(*_course_of(row))
                course_counts[label][ptype] += 1
                treatment_amount += fee_for_label(label)
        course_counts = {lb: dict(d) for lb, d in course_counts.items()}

        # 民眾明細:依固定類型順序,(姓名+身分證+類型+費率) 去重。
        # 費率要進 key —— 同一位民眾同一類處方若分別做了一般課程與 PLUS2,
        # 是兩筆不同單價的給付,不能被去重吃掉,否則明細人次會少於計費人次、
        # 明細表的算式跟領據金額對不起來。
        patients = []
        seen = set()
        for ptype in sorted(type_records.keys(),
                            key=lambda t: PTYPE_INDEX.get(t, 99)):
            for row in type_records[ptype]:
                row_label = classify_course(*_course_of(row))
                key = (row[COL_NAME], row[COL_ID], ptype, row_label)
                if key in seen:
                    continue
                seen.add(key)
                patients.append(PatientRecord(
                    name=str(row[COL_NAME] or ""),
                    id_number=str(row[COL_ID] or ""),
                    birth_date=str(row[COL_BIRTH] or ""),
                    prescriber=str(row[COL_DOCTOR] or ""),
                    exec_date=str(row[COL_EXEC_DATE] or ""),
                    prescription_type=ptype,
                    course_label=row_label,
                ))

        # 主要類型(僅供標題等備註,實際金額/份數以 type_counts 為準)
        main_type = (
            max(type_counts, key=lambda t: (type_counts[t],
                                             -PTYPE_INDEX.get(t, 99)))
            if type_counts else ""
        )

        exec_receipt = ReceiptInfo(
            recipient_name=exec_person,
            amount=treatment_amount,
        )

        executors.append(ExecutorData(
            executor_name=exec_person,
            prescription_type=main_type,
            service_count=total_service,
            type_counts=type_counts,
            course_counts=course_counts,
            patients=patients,
            receipt=exec_receipt,
        ))

    return AllData(
        report_year=report_year,
        report_month=report_month,
        doctors=doctors,
        health_mgmts=health_mgmts,
        executors=executors,
        min_prescriptions=min_prescriptions,
    )
