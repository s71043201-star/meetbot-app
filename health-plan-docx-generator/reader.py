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
from config import FEE_PER_PRESCRIPTION, FEE_PER_EXECUTION, FEE_PER_TREATMENT

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
COL_EXEC_DATE = 16
COL_PRESC_FEE = 17   # 處方費（每筆金額）
COL_EXEC_FEE = 18    # 處方執行費（每筆金額）
COL_DATE = 21


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


def read_prescription_report(issuance_path: str,
                             execution_path: str = "",
                             report_year: int = 115,
                             report_month: int = 4,
                             min_prescriptions: int = 0) -> AllData:
    """讀取處方紀錄並統計。

    - issuance_path: 開立處方紀錄 Excel（必要）— 計算處方費 + 健康管理費
    - execution_path: 執行處方紀錄 Excel（選填）— 計算處方執行費 + 處方處置費
                     若空，issuance_path 兼作執行紀錄（單檔舊行為）
    """
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
        doctor = str(row[COL_DOCTOR] or "")
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
        doctor = str(row[COL_DOCTOR] or "")
        if ptype not in PRESCRIPTION_TYPES:
            continue

        exec_done = row[COL_EXEC_DONE]
        exec_person = row[COL_EXEC_PERSON]
        exec_unit = row[COL_EXEC_UNIT]
        if not (exec_done and exec_person):
            continue

        doctor_execution[(clinic, doctor)][ptype] += 1
        doctor_records_execution[(clinic, doctor)].append(row)
        executor_records[(str(exec_unit or ""), str(exec_person))][ptype].append(row)
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
                out.append(PatientRecord(
                    name=str(row[COL_NAME] or ""),
                    id_number=str(row[COL_ID] or ""),
                    birth_date=str(row[COL_BIRTH] or ""),
                    prescriber=doctor_name,
                    exec_date=str(row[COL_EXEC_DATE] or ""),
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
            unique_patients.add(row[COL_NAME])
            if not admin_person:
                # 診所人員：暫用開立醫師，之後由個資檔反查表覆蓋正確人名
                admin_person = str(row[COL_DOCTOR] or "")

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
            hm_patients.append(PatientRecord(
                name=str(row[COL_NAME] or ""),
                id_number=str(row[COL_ID] or ""),
                birth_date=str(row[COL_BIRTH] or ""),
                prescriber=str(row[COL_DOCTOR] or ""),
                exec_date=str(row[COL_EXEC_DATE] or ""),
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
    executors = []
    for (exec_unit, exec_person), type_records in sorted(executor_records.items()):
        total_service = sum(len(recs) for recs in type_records.values())
        # 取得這位執行人員的民眾明細
        patients = []
        seen = set()
        for ptype, recs in type_records.items():
            for row in recs:
                key = (row[COL_NAME], row[COL_ID], ptype)
                if key not in seen:
                    seen.add(key)
                    patients.append(PatientRecord(
                        name=str(row[COL_NAME] or ""),
                        id_number=str(row[COL_ID] or ""),
                        birth_date=str(row[COL_BIRTH] or ""),
                        prescriber=str(row[COL_DOCTOR] or ""),
                        exec_date=str(row[COL_EXEC_DATE] or ""),
                        prescription_type=ptype,
                    ))

        # 判斷主要處方類型
        main_type = max(type_records.keys(),
                        key=lambda t: len(type_records[t]))

        exec_receipt = ReceiptInfo(
            recipient_name=exec_person,
            amount=total_service * FEE_PER_TREATMENT,
        )

        executors.append(ExecutorData(
            executor_name=exec_person,
            prescription_type=main_type,
            service_count=total_service,
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
