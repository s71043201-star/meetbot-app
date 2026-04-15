"""從系統匯出的處方紀錄 Excel 讀取並統計資料

Excel 格式（單一 sheet「處方紀錄」）：
欄位：流水號 | 姓名 | 性別 | 生日 | 身分證字號 | 手機 | 處方類型 |
      開立診所 | 開立醫師 | 是否選課 | 選課名稱 | 選課時段 |
      執行單位 | 執行人員 | 執行處方 | 執行課程 | 執行日期 |
      處方費 | 處方執行費 | 處方處置費 | 已核銷 | 開立日期時間
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import openpyxl

from models import AllData, DoctorPrescription, HealthManagement, ExecutorData, PatientRecord, ReceiptInfo

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
COL_DATE = 21


def read_prescription_report(filepath: str,
                             report_year: int = 115,
                             report_month: int = 4,
                             min_prescriptions: int = 0) -> AllData:
    """讀取處方紀錄 Excel 並統計所有資料"""

    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb["處方紀錄"]

    # 收集所有資料列
    records = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        records.append(row)
    wb.close()

    # === 1. 按醫師統計處方開立費 ===
    # key: (診所, 醫師) → {處方類型: 開立份數}
    doctor_prescription = defaultdict(lambda: defaultdict(int))
    # key: (診所, 醫師) → {處方類型: 執行份數}
    doctor_execution = defaultdict(lambda: defaultdict(int))
    # key: 診所 → 所有記錄
    clinic_records = defaultdict(list)
    # key: (執行單位, 執行人員) → {處方類型: [records]}
    executor_records = defaultdict(lambda: defaultdict(list))

    for row in records:
        ptype = str(row[COL_PTYPE] or "")
        clinic = str(row[COL_CLINIC] or "")
        doctor = str(row[COL_DOCTOR] or "")

        if ptype not in PRESCRIPTION_TYPES:
            continue

        # 處方開立
        doctor_prescription[(clinic, doctor)][ptype] += 1
        clinic_records[clinic].append(row)

        # 處方執行（有執行日期 = 已執行）
        exec_done = row[COL_EXEC_DONE]
        exec_person = row[COL_EXEC_PERSON]
        exec_unit = row[COL_EXEC_UNIT]
        if exec_done and exec_person:
            doctor_execution[(clinic, doctor)][ptype] += 1
            executor_records[(str(exec_unit or ""), str(exec_person))][ptype].append(row)

    # === 2. 建立 DoctorPrescription 列表 ===
    doctors = []
    for (clinic, doctor_name), type_counts in sorted(doctor_prescription.items()):
        exec_counts = doctor_execution.get((clinic, doctor_name), {})
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
        ))

    # === 3. 健康管理費（按診所統計）===
    health_mgmts = []
    for clinic, rows in sorted(clinic_records.items()):
        unique_patients = set()
        admin_person = ""
        for row in rows:
            unique_patients.add(row[COL_NAME])
            if not admin_person:
                admin_person = str(row[COL_DOCTOR] or "")

        total_count = len(rows)
        people_count = len(unique_patients)

        if min_prescriptions > 0 and total_count < min_prescriptions:
            continue

        health_mgmts.append(HealthManagement(
            medical_institution=clinic,
            clinic_person=admin_person,
            prescription_people=people_count,
            prescription_count=total_count,
            is_qualified=True,
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
                    ))

        # 判斷主要處方類型
        main_type = max(type_records.keys(),
                        key=lambda t: len(type_records[t]))

        exec_receipt = ReceiptInfo(
            recipient_name=exec_person,
            amount=total_service * 400,
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
    )
