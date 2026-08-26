from docx.shared import Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn

from models import AllData, DoctorPrescription, HealthManagement
from templates.doc_utils import (
    compact_paragraph,
    create_document, add_title, add_run, set_cell_text,
    set_table_borders, set_col_widths, add_info_table, add_page_break,
    add_signature_line, add_note, today_roc,
)

from config import FEE_PER_PRESCRIPTION, FEE_PER_EXECUTION, HEALTH_MGMT_FEE, PEOPLE_DIVISOR

PRESCRIPTION_TYPES = ["運動處方", "營養處方", "情緒調適處方", "社會處方"]

# Column widths from actual document (EMU)
DATA_COL_WIDTHS = [1496060, 3004185, 2007235, 2493010]


def generate_prescription_fee_doc(data: AllData, output_path: str):
    """產生處方費核銷總表 — 每位醫師一頁"""
    doc = create_document()
    year, month, day = today_roc()

    for i, doctor in enumerate(data.doctors):
        if i > 0:
            add_page_break(doc)
        _add_prescription_fee_page(doc, data, doctor)

    doc.save(output_path)


def generate_execution_fee_doc(data: AllData, output_path: str):
    """產生處方執行費核銷總表 — 每位醫師一頁"""
    doc = create_document()

    for i, doctor in enumerate(data.doctors):
        if i > 0:
            add_page_break(doc)
        _add_execution_fee_page(doc, data, doctor)

    doc.save(output_path)


def generate_health_mgmt_doc(data: AllData, output_path: str,
                             min_prescriptions: int = 0):
    """產生健康管理費總表"""
    doc = create_document()

    for i, hm in enumerate(data.health_mgmts):
        if i > 0:
            add_page_break(doc)
        _add_health_mgmt_page(doc, data, hm, min_prescriptions=min_prescriptions)

    doc.save(output_path)


def generate_patient_list_doc(data: AllData, output_path: str):
    """產生民眾明細表"""
    doc = create_document()
    _add_patient_list_page(doc, data)
    doc.save(output_path)


def generate_receipt_doc(data: AllData, output_path: str):
    """產生診所端領據"""
    doc = create_document()
    if data.clinic_receipt:
        _add_receipt_page(doc, data)
    doc.save(output_path)


# ── Internal page builders ──────────────────────────────────────


def _add_prescription_fee_page(doc, data: AllData, doctor: DoctorPrescription):
    period = f"{data.report_year}年{data.report_month}月"

    add_title(doc, "台北市醫師公會健康台灣深耕計畫")
    add_title(doc, "臺北市慢性病防治全人健康智慧整合照護計畫")
    add_title(doc, f"{data.report_year}年{data.report_month:02d}月處方費核銷總表")

    p = doc.add_paragraph(); compact_paragraph(p)
    add_info_table(doc, [
        ("醫療機構", doctor.medical_institution),
        ("申報期間", period),
        ("開立醫師", doctor.doctor_name),
    ])
    p = doc.add_paragraph(); compact_paragraph(p)

    counts = [doctor.exercise, doctor.nutrition, doctor.emotion, doctor.social]
    amounts = [c * FEE_PER_PRESCRIPTION for c in counts]
    total_count = sum(counts)
    total_amount = sum(amounts)

    table = doc.add_table(rows=6, cols=4)
    set_table_borders(table)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_col_widths(table, DATA_COL_WIDTHS)

    headers = ["編號", "處方類型", "開立份數", "申報金額(元)"]
    for i, h in enumerate(headers):
        set_cell_text(table.cell(0, i), h, bold=True)

    for i, (ptype, count, amount) in enumerate(
        zip(PRESCRIPTION_TYPES, counts, amounts)
    ):
        set_cell_text(table.cell(i + 1, 0), str(i + 1))
        set_cell_text(table.cell(i + 1, 1), ptype, align="left")
        set_cell_text(table.cell(i + 1, 2), str(count))
        set_cell_text(table.cell(i + 1, 3), f"${amount:,}")

    set_cell_text(table.cell(5, 0), "總計", bold=True)
    set_cell_text(table.cell(5, 1), "總計", bold=True)
    set_cell_text(table.cell(5, 2), str(total_count), bold=True)
    set_cell_text(table.cell(5, 3), f"${total_amount:,}", bold=True)

    p = doc.add_paragraph(); compact_paragraph(p)
    add_note(doc, [
        f"處方費計算方式:開立人數 × 每份處方費{FEE_PER_PRESCRIPTION}元",
        "本表不含個人資料，僅供核銷統計使用",
    ])


def _add_execution_fee_page(doc, data: AllData, doctor: DoctorPrescription):
    period = f"{data.report_year}年{data.report_month}月"

    add_title(doc, "台北市醫師公會健康台灣深耕計畫")
    add_title(doc, "臺北市慢性病防治全人健康智慧整合照護計畫")
    add_title(doc, f"{data.report_year}年{data.report_month:02d}月處方執行費核銷總表")

    p = doc.add_paragraph(); compact_paragraph(p)
    add_info_table(doc, [
        ("醫療機構", doctor.medical_institution),
        ("申報期間", period),
        ("開立醫師", doctor.doctor_name),
    ])
    p = doc.add_paragraph(); compact_paragraph(p)

    # 執行費的順序: 營養 → 運動 → 情緒調適 → 社會
    types_exec = ["營養處方", "運動處方", "情緒調適處方", "社會處方"]
    counts = [
        doctor.nutrition_exec, doctor.exercise_exec,
        doctor.emotion_exec, doctor.social_exec,
    ]
    amounts = [c * FEE_PER_EXECUTION for c in counts]
    total_count = sum(counts)
    total_amount = sum(amounts)

    table = doc.add_table(rows=6, cols=4)
    set_table_borders(table)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_col_widths(table, DATA_COL_WIDTHS)

    headers = ["編號", "處方類型", "執行份數", "申報金額(元)"]
    for i, h in enumerate(headers):
        set_cell_text(table.cell(0, i), h, bold=True)

    for i, (ptype, count, amount) in enumerate(
        zip(types_exec, counts, amounts)
    ):
        set_cell_text(table.cell(i + 1, 0), str(i + 1))
        set_cell_text(table.cell(i + 1, 1), ptype, align="left")
        set_cell_text(table.cell(i + 1, 2), str(count))
        set_cell_text(table.cell(i + 1, 3), f"${amount:,}")

    set_cell_text(table.cell(5, 0), "總計", bold=True)
    set_cell_text(table.cell(5, 1), "總計", bold=True)
    set_cell_text(table.cell(5, 2), str(total_count), bold=True)
    set_cell_text(table.cell(5, 3), f"${total_amount:,}", bold=True)

    p = doc.add_paragraph(); compact_paragraph(p)
    add_note(doc, [
        f"處方執行費計算方式:執行人數 × 每份處方費{FEE_PER_EXECUTION}元",
        "本表不含個人資料，僅供核銷統計使用",
    ])


def _add_health_mgmt_page(doc, data: AllData, hm: HealthManagement,
                          min_prescriptions: int = 0):
    period = f"{data.report_year}年{data.report_month}月"

    add_title(doc, "台北市醫師公會健康台灣深耕計畫")
    add_title(doc, "臺北市慢性病防治全人健康智慧整合照護計畫")
    add_title(doc, f"健康處方管理費總表-{hm.clinic_person}")

    p = doc.add_paragraph(); compact_paragraph(p)
    add_info_table(doc, [
        ("醫療機構", hm.medical_institution),
        ("申報期間", period),
        ("診所人員", hm.clinic_person),
    ])
    p = doc.add_paragraph(); compact_paragraph(p)

    table = doc.add_table(rows=3, cols=5)
    set_table_borders(table)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    # 欄寬與範本一致：41.6 / 83.4 / 39.4 / 32.5 / 53.1 mm
    set_col_widths(table, [1496060, 3004185, 1417320, 1170940, 1911350])

    headers = ["編號", "處方類型", "開立處方人數", "開立份數", "達標"]
    for i, h in enumerate(headers):
        set_cell_text(table.cell(0, i), h, bold=True)

    set_cell_text(table.cell(1, 0), "1")
    set_cell_text(table.cell(1, 1), "運動、營養、社會、情緒調適處方", align="left")
    set_cell_text(table.cell(1, 2), str(hm.prescription_people))
    set_cell_text(table.cell(1, 3), str(hm.prescription_count))
    set_cell_text(table.cell(1, 4), "是" if hm.is_qualified else "否")

    set_cell_text(table.cell(2, 0), "")
    set_cell_text(table.cell(2, 1), "總計", bold=True)
    set_cell_text(table.cell(2, 2), "")
    set_cell_text(table.cell(2, 3), "")
    amount = f"${HEALTH_MGMT_FEE:,}" if hm.is_qualified else "$0"
    set_cell_text(table.cell(2, 4), amount, bold=True)

    p = doc.add_paragraph(); compact_paragraph(p)
    if min_prescriptions:
        min_people = min_prescriptions // PEOPLE_DIVISOR
        min_count = min_prescriptions
    else:
        min_people = "X"
        min_count = "XX"
    add_note(doc, [
        f"處方執行費計算方式：每個月開立處方 {min_people} 人以上 {min_count} 份處方，健康管理費${HEALTH_MGMT_FEE:,}",
        "本表不含個人資料，僅供核銷統計使用",
    ])


def _cell_grid(table):
    """一次建表儲存格再以索引存取，避免 table.cell() 大表 O(n²) 燒 CPU。"""
    cells = table._cells
    ncol = table._column_count
    return lambda r, c: cells[r * ncol + c]


def _add_patient_list_page(doc, data: AllData):
    add_title(doc, "民眾明細表", size=14)
    p = doc.add_paragraph(); compact_paragraph(p)

    num_patients = len(data.patients)
    table = doc.add_table(rows=num_patients + 1, cols=5)
    set_table_borders(table)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    cell_at = _cell_grid(table)
    headers = ["序號", "民眾姓名", "民眾身分證字號",
               "民眾出生年月日(yyyy/mm/dd)", "處方人員姓名"]
    for i, h in enumerate(headers):
        set_cell_text(cell_at(0, i), h, bold=True, font_size=10)

    for i, p in enumerate(data.patients):
        set_cell_text(cell_at(i + 1, 0), str(i + 1), font_size=10)
        set_cell_text(cell_at(i + 1, 1), p.name, font_size=10)
        set_cell_text(cell_at(i + 1, 2), p.id_number, font_size=10)
        set_cell_text(cell_at(i + 1, 3), p.birth_date, font_size=10)
        set_cell_text(cell_at(i + 1, 4), p.prescriber, font_size=10)

    set_col_widths(table, [Cm(1.5), Cm(3), Cm(4), Cm(4.5), Cm(3)])

    p = doc.add_paragraph(); compact_paragraph(p)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_run(p, f"總服務人次：{num_patients} 人")

    p = doc.add_paragraph(); compact_paragraph(p)
    add_signature_line(doc, "執行人員確認簽章")


def _add_receipt_page(doc, data: AllData):
    receipt = data.clinic_receipt

    # Header
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    add_run(p, "個人核銷領據(不扣稅)", size=10)

    add_title(doc, "領　　　據", size=22)

    p = doc.add_paragraph()
    add_run(
        p,
        f"茲收到 {data.report_year} 年 {data.report_month} 月台北市醫師公會"
        "「健康台灣深耕計畫」"
        "-臺北市慢性病防治全人健康智慧整合照護計畫",
        size=14,
    )

    p = doc.add_paragraph()
    add_run(p, f"應付新臺幣 {receipt.amount:,} 元整。", size=14)

    p = doc.add_paragraph(); compact_paragraph(p)

    p = doc.add_paragraph()
    add_run(p, "此　　致", size=14)

    p = doc.add_paragraph()
    add_run(p, "台北市醫師公會", size=14)

    p = doc.add_paragraph(); compact_paragraph(p)

    fields = [
        ("具領人", receipt.recipient_name),
        ("身分證字號", receipt.id_number),
        ("戶籍地址", receipt.address),
        ("聯絡電話", receipt.phone),
        ("戶名", receipt.account_name),
        ("銀行及分行", receipt.bank_branch),
        ("銀行代碼", receipt.bank_code),
        ("帳號", receipt.account_number),
    ]

    table = doc.add_table(rows=len(fields), cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, (label, value) in enumerate(fields):
        set_cell_text(table.cell(i, 0), f"{label}：", bold=True, align="right",
                      font_size=14)
        set_cell_text(table.cell(i, 1), value, align="left", font_size=14)
    set_col_widths(table, [Cm(4), Cm(8)])

    p = doc.add_paragraph(); compact_paragraph(p)
    p = doc.add_paragraph()
    add_run(p, "(請檢附帳戶存摺影本)", size=14, bold=True)

    p = doc.add_paragraph(); compact_paragraph(p)

    p = doc.add_paragraph()
    add_run(p, "具領人用印：_____________", size=14)

    p = doc.add_paragraph(); compact_paragraph(p)

    year, m, d = today_roc()
    p = doc.add_paragraph()
    add_run(p, f"中　華　民　國　　　{year}　年　　{m}　月　　{d}　日", size=14)
