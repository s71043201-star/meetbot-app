"""執行人員端文件產生器

每位執行人員輸出：
- Word：核銷總表（直式）、明細表（直式）、領據（直式，模板）各一份
- PDF：三份 Word 各自轉 PDF 再合併成一份
"""

import os

from docx.shared import Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

from models import AllData, ExecutorData, ReceiptInfo
from templates.doc_utils import (
    compact_paragraph,
    create_document, add_title, add_run, set_cell_text,
    set_table_borders, set_col_widths, add_info_table, add_page_break,
    add_signature_line, add_note, today_roc,
)
from templates.receipt import generate_receipt

FEE_PER_TREATMENT = 400
# 直式 A4 邊距 1.5cm，可用寬度約 18cm ≈ 6,480,000 EMU
DATA_COL_WIDTHS = [950000, 2100000, 1400000, 1750000]
PATIENT_COL_WIDTHS = [450000, 950000, 1200000, 1500000, 1100000, 1280000]


def generate_treatment_fee_doc(data: AllData, output_path: str):
    """產生所有執行人員的處方處置費核銷總表（合併成一份 Word）"""
    doc = create_document(landscape=False)
    for section in doc.sections:
        section.left_margin = Cm(1.5)
        section.right_margin = Cm(1.5)

    first = True
    for executor in data.executors:
        if not executor.receipt or executor.receipt.amount <= 0:
            continue
        if not first:
            add_page_break(doc)
        _add_treatment_fee_page(doc, data, executor)
        first = False

    doc.save(output_path)


def generate_executor_patient_list_doc(data: AllData, output_path: str):
    """產生所有執行人員的民眾明細表（合併成一份 Word）"""
    doc = create_document(landscape=False)
    for section in doc.sections:
        section.left_margin = Cm(1.5)
        section.right_margin = Cm(1.5)

    first = True
    for executor in data.executors:
        if not executor.receipt or executor.receipt.amount <= 0:
            continue
        if not first:
            add_page_break(doc)
        _add_patient_list_page(doc, data, executor)
        first = False

    doc.save(output_path)


def generate_doctor_receipts(data: AllData,
                             presc_dir: str, exec_dir: str,
                             receipt_lookup: dict | None = None):
    """產生每位醫師的處方費（→presc_dir）+ 處方執行費（→exec_dir）領據，各自轉 PDF"""
    from templates.receipt import generate_receipt
    from dataclasses import replace

    for doc_data in data.doctors:
        name = doc_data.doctor_name
        base_receipt = ReceiptInfo(recipient_name=name)

        # 從個資檔補入個人資料
        if receipt_lookup and name in receipt_lookup:
            prev = receipt_lookup[name]
            base_receipt = replace(
                base_receipt,
                id_number=prev.id_number,
                address=prev.address,
                phone=prev.phone,
                account_name=prev.account_name,
                bank_branch=prev.bank_branch,
                bank_code=prev.bank_code,
                account_number=prev.account_number,
            )

        docx_to_convert = []

        # 處方費領據 → 處方費領據資料夾
        if doc_data.prescription_fee > 0:
            receipt = replace(base_receipt, amount=doc_data.prescription_fee)
            out = os.path.join(presc_dir, f"{name}_處方費領據.docx")
            generate_receipt(receipt, data.report_year, data.report_month,
                             out, fee_type="運動、營養、社會情緒調適處方處方費")
            docx_to_convert.append(out)

        # 處方執行費領據 → 處方執行費領據資料夾
        if doc_data.execution_fee > 0:
            receipt = replace(base_receipt, amount=doc_data.execution_fee)
            out = os.path.join(exec_dir, f"{name}_處方執行費領據.docx")
            generate_receipt(receipt, data.report_year, data.report_month,
                             out, fee_type="運動、營養、社會情緒調適處方處方執行費")
            docx_to_convert.append(out)

        # 各自轉成獨立 PDF
        if docx_to_convert:
            _convert_docx_list_to_pdf(docx_to_convert)


def _convert_docx_list_to_pdf(docx_paths: list):
    """將多份 docx 各自轉成獨立 PDF（不合併，醫師領據用）"""
    try:
        import win32com.client
    except ImportError:
        return
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        for docx_path in docx_paths:
            pdf_path = docx_path.replace(".docx", ".pdf")
            try:
                wdoc = word.Documents.Open(os.path.abspath(docx_path))
                wdoc.SaveAs(os.path.abspath(pdf_path), FileFormat=17)
                wdoc.Close()
            except Exception:
                pass
    finally:
        word.Quit()


def _merge_docx_to_pdf(docx_paths: list, output_dir: str, name: str):
    """將多份 docx 轉成 PDF 後合併"""
    try:
        import win32com.client
        import PyPDF2
    except ImportError:
        return

    pdf_paths = []
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        for docx_path in docx_paths:
            pdf_path = docx_path.replace(".docx", ".pdf")
            try:
                wdoc = word.Documents.Open(os.path.abspath(docx_path))
                wdoc.SaveAs(os.path.abspath(pdf_path), FileFormat=17)
                wdoc.Close()
                pdf_paths.append(pdf_path)
            except Exception:
                pass
    finally:
        word.Quit()

    if len(pdf_paths) >= 2:
        merged_path = os.path.join(output_dir, f"{name}_領據合併.pdf")
        merger = PyPDF2.PdfMerger()
        for p in pdf_paths:
            merger.append(p)
        merger.write(merged_path)
        merger.close()


def generate_executor_receipts(data: AllData, output_dir: str,
                               receipt_lookup: dict | None = None):
    """只產生每位執行人員的領據 .docx（不合併 PDF）

    receipt_lookup: {姓名: ReceiptInfo}，從舊領據讀入，自動帶入個人資料
    """
    for executor in data.executors:
        if not executor.receipt or executor.receipt.amount <= 0:
            continue

        name = executor.executor_name
        receipt = executor.receipt

        if receipt_lookup and name in receipt_lookup:
            prev = receipt_lookup[name]
            from dataclasses import replace
            receipt = replace(
                receipt,
                recipient_name=receipt.recipient_name or prev.recipient_name or name,
                id_number=receipt.id_number or prev.id_number,
                address=receipt.address or prev.address,
                phone=receipt.phone or prev.phone,
                account_name=receipt.account_name or prev.account_name,
                bank_branch=receipt.bank_branch or prev.bank_branch,
                bank_code=receipt.bank_code or prev.bank_code,
                account_number=receipt.account_number or prev.account_number,
            )

        from templates.receipt import generate_receipt
        out_path = os.path.join(output_dir, f"{name}_領據.docx")
        generate_receipt(
            receipt, data.report_year, data.report_month,
            out_path, fee_type=executor.prescription_type + "處方處方處置費",
        )


def generate_executor_merged_docs(data: AllData, output_dir: str,
                                  also_pdf: bool = True,
                                  receipt_lookup: dict | None = None):
    """每位執行人員產生 Word + 合併 PDF

    receipt_lookup: {姓名: ReceiptInfo}，從舊領據讀入，自動帶入個人資料
    """

    for executor in data.executors:
        if not executor.receipt or executor.receipt.amount <= 0:
            continue

        name = executor.executor_name
        tmp_dir = os.path.join(output_dir, "_tmp")
        os.makedirs(tmp_dir, exist_ok=True)

        # 若有舊領據查找表，將個人資料帶入（保留本月金額）
        receipt = executor.receipt
        if receipt_lookup and name in receipt_lookup:
            prev = receipt_lookup[name]
            from dataclasses import replace
            receipt = replace(
                receipt,
                recipient_name=receipt.recipient_name or prev.recipient_name or name,
                id_number=receipt.id_number or prev.id_number,
                address=receipt.address or prev.address,
                phone=receipt.phone or prev.phone,
                account_name=receipt.account_name or prev.account_name,
                bank_branch=receipt.bank_branch or prev.bank_branch,
                bank_code=receipt.bank_code or prev.bank_code,
                account_number=receipt.account_number or prev.account_number,
            )
            pass

        # === Word 1: 核銷總表 + 明細表（直式，縮小邊距）===
        doc = create_document(landscape=False)
        for section in doc.sections:
            section.left_margin = Cm(1.5)
            section.right_margin = Cm(1.5)
        _add_treatment_fee_page(doc, data, executor)
        add_page_break(doc)
        _add_patient_list_page(doc, data, executor)
        main_docx = os.path.abspath(os.path.join(tmp_dir, f"{name}_總表.docx"))
        doc.save(main_docx)

        # === Word 2: 領據（直式，用模板）===
        receipt_docx = os.path.abspath(
            os.path.join(tmp_dir, f"{name}_領據.docx"))
        generate_receipt(
            receipt, data.report_year, data.report_month,
            receipt_docx, fee_type=executor.prescription_type,
        )

        # === 合併 PDF ===
        if also_pdf:
            try:
                _make_merged_pdf(
                    main_docx, receipt_docx,
                    output_dir, executor.prescription_type, name,
                )
            except Exception as e:
                print(f"  [WARN] {name} PDF 失敗: {e}")

    # 清理暫存目錄
    tmp_dir = os.path.join(output_dir, "_tmp")
    if os.path.exists(tmp_dir):
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _make_merged_pdf(main_docx, receipt_docx, output_dir, ptype, name):
    """兩份 Word 各自轉 PDF，再合併"""
    import win32com.client
    from PyPDF2 import PdfMerger

    tmp_dir = os.path.dirname(main_docx)
    main_pdf = os.path.join(tmp_dir, f"{name}_總表.pdf")
    receipt_pdf = os.path.join(tmp_dir, f"{name}_領據.pdf")

    # Word → PDF（共用一個 Word instance）
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        for docx, pdf in [(main_docx, main_pdf), (receipt_docx, receipt_pdf)]:
            doc = word.Documents.Open(docx)
            doc.SaveAs(pdf, FileFormat=17)
            doc.Close()
    finally:
        word.Quit()

    # 合併 PDF，按處方類型分資料夾
    pdf_dir = os.path.join(output_dir, "PDF", ptype)
    os.makedirs(pdf_dir, exist_ok=True)
    final_pdf = os.path.join(pdf_dir, f"{name}.pdf")

    merger = PdfMerger()
    merger.append(main_pdf)
    merger.append(receipt_pdf)
    merger.write(final_pdf)
    merger.close()


# ── Page builders ──────────────────────────────────────


def _add_treatment_fee_page(doc, data: AllData, executor: ExecutorData):
    period = f"{data.report_year}年{data.report_month}月"

    add_title(doc, "台北市醫師公會健康台灣深耕計畫", size=16)
    add_title(doc, "臺北市慢性病防治全人健康智慧整合照護計畫", size=16)
    add_title(doc,
              f"{data.report_year}年{data.report_month:02d}月處方處置費核銷總表",
              size=16)

    p = doc.add_paragraph(); compact_paragraph(p)
    info_total = sum(DATA_COL_WIDTHS)
    add_info_table(doc, [
        ("執行人員", executor.executor_name),
        ("申報期間", period),
    ], col_widths=[info_total // 4, info_total * 3 // 4], font_size=12)
    p = doc.add_paragraph(); compact_paragraph(p)

    amount = executor.service_count * FEE_PER_TREATMENT

    table = doc.add_table(rows=3, cols=4)
    set_table_borders(table)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_col_widths(table, DATA_COL_WIDTHS)

    headers = ["編號", "處方類型", "服務人次", "申報金額(元)"]
    for i, h in enumerate(headers):
        set_cell_text(table.cell(0, i), h, bold=True, font_size=14)

    set_cell_text(table.cell(1, 0), "1", font_size=14)
    set_cell_text(table.cell(1, 1), executor.prescription_type, align="left", font_size=14)
    set_cell_text(table.cell(1, 2), str(executor.service_count), font_size=14)
    set_cell_text(table.cell(1, 3), f"${amount:,}", font_size=14)

    set_cell_text(table.cell(2, 0), "", font_size=14)
    set_cell_text(table.cell(2, 1), "總計", bold=True, font_size=14)
    set_cell_text(table.cell(2, 2), str(executor.service_count), bold=True, font_size=14)
    set_cell_text(table.cell(2, 3), f"${amount:,}", bold=True, font_size=14)

    p = doc.add_paragraph(); compact_paragraph(p)
    add_note(doc, [
        f"處方處置費計算方式：服務人次 × 每人次處置費 {FEE_PER_TREATMENT} 元",
        "本表不含個人資料，僅供核銷統計使用",
    ], font_size=12)


def _add_patient_list_page(doc, data: AllData, executor: ExecutorData):
    patients = executor.patients
    num = len(patients)
    amount = executor.service_count * FEE_PER_TREATMENT
    prefix = f"{data.report_year}年{data.report_month:02d}月"

    # 標頭
    add_title(doc, "台北市醫師公會健康台灣深耕計畫", size=16)
    add_title(doc, "臺北市慢性病防治全人健康智慧整合照護計畫", size=16)
    add_title(doc,
              f"{executor.prescription_type}處方處置費總表-{executor.executor_name}",
              size=16)

    # 表格 6 欄（含執行日期）
    num_rows = max(num, 8) + 1
    table = doc.add_table(rows=num_rows, cols=6)
    set_table_borders(table)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_col_widths(table, PATIENT_COL_WIDTHS)

    fs = 12  # 直式頁面 6 欄字體
    headers = ["序號", "民眾姓名", "出生日期",
               "處方類型", "處方人員", "執行日期"]
    for i, h in enumerate(headers):
        set_cell_text(table.cell(0, i), h, bold=True, font_size=fs)

    for i, p in enumerate(patients):
        set_cell_text(table.cell(i + 1, 0), str(i + 1), font_size=fs)
        set_cell_text(table.cell(i + 1, 1), p.name, font_size=fs)
        set_cell_text(table.cell(i + 1, 2), p.birth_date, font_size=fs)
        set_cell_text(table.cell(i + 1, 3), executor.prescription_type, font_size=fs)
        set_cell_text(table.cell(i + 1, 4), executor.executor_name, font_size=fs)
        exec_date = getattr(p, "exec_date", "")
        set_cell_text(table.cell(i + 1, 5), str(exec_date), font_size=fs)

    # 底部摘要 — 靠左、粗體
    p_elem = doc.add_paragraph()
    p_elem.alignment = WD_ALIGN_PARAGRAPH.LEFT
    compact_paragraph(p_elem)
    add_run(p_elem, f"總服務人次：{num}人", size=12, bold=True)

    p_elem = doc.add_paragraph()
    p_elem.alignment = WD_ALIGN_PARAGRAPH.LEFT
    compact_paragraph(p_elem)
    add_run(
        p_elem,
        f"{prefix}{executor.prescription_type}處方處置費總申報金額（元）：{amount:,}",
        size=12, bold=True,
    )

