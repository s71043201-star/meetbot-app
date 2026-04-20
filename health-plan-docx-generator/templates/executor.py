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
from config import FEE_PER_TREATMENT
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
                             month_dir: str,
                             receipt_lookup: dict | None = None,
                             also_pdf: bool = True,
                             progress_cb=None):
    """每位醫師產生拆分的 Word（各自存在不同資料夾）+ 合併 PDF

    資料夾結構（month_dir 下）：
      [處方費]
      處方費核銷總表/{醫師}_核銷總表.docx + .pdf       (個別，單頁 per-doctor)
      處方費民眾明細/{醫師}_民眾明細.docx + .pdf
      處方費領據/{醫師}_處方費領據.docx + .pdf
      處方費領據/PDF/{醫師}.pdf                        (合併：總表+明細+領據)

      [處方執行費]
      處方執行費核銷總表/{醫師}_核銷總表.docx + .pdf
      處方執行費民眾明細/{醫師}_民眾明細.docx + .pdf
      處方執行費領據/{醫師}_處方執行費領據.docx + .pdf
      處方執行費領據/PDF/{醫師}.pdf                    (合併：總表+明細+領據)
    """
    from templates.receipt import generate_receipt
    from templates.clinic import _add_prescription_fee_page, _add_execution_fee_page
    from dataclasses import replace

    # 子資料夾
    presc_total_dir   = os.path.join(month_dir, "處方費核銷總表")
    presc_detail_dir  = os.path.join(month_dir, "處方費民眾明細")
    presc_receipt_dir = os.path.join(month_dir, "處方費領據")
    exec_total_dir    = os.path.join(month_dir, "處方執行費核銷總表")
    exec_detail_dir   = os.path.join(month_dir, "處方執行費民眾明細")
    exec_receipt_dir  = os.path.join(month_dir, "處方執行費領據")
    for d in [presc_total_dir, presc_detail_dir, presc_receipt_dir,
              exec_total_dir, exec_detail_dir, exec_receipt_dir]:
        os.makedirs(d, exist_ok=True)

    # 蒐集每位醫師的 docx 路徑（kind: "presc" / "exec"）
    # list of (kind, name, total_docx, detail_docx, receipt_docx, receipt_dir)
    docx_info = []

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

        # === 處方費 ===
        if doc_data.prescription_fee > 0:
            # 核銷總表（單人單頁，橫向 — 配合既有的 4 欄寬度設計）
            total_docx = os.path.join(presc_total_dir, f"{name}_核銷總表.docx")
            doc = create_document()
            _add_prescription_fee_page(doc, data, doc_data)
            doc.save(total_docx)

            # 民眾明細（單人，直式 + 縮邊距 — 配合 PATIENT_COL_WIDTHS）
            detail_docx = os.path.join(presc_detail_dir, f"{name}_民眾明細.docx")
            doc = create_document(landscape=False)
            for section in doc.sections:
                section.left_margin = Cm(1.5)
                section.right_margin = Cm(1.5)
            _add_doctor_patient_list_page(doc, data, doc_data, fee_label="處方費")
            doc.save(detail_docx)

            # 領據
            receipt = replace(base_receipt, amount=doc_data.prescription_fee)
            receipt_docx = os.path.join(presc_receipt_dir, f"{name}_處方費領據.docx")
            generate_receipt(receipt, data.report_year, data.report_month,
                             receipt_docx,
                             fee_type="運動、營養、社會、情緒調適處方處方費")

            docx_info.append((
                "presc", name,
                os.path.abspath(total_docx),
                os.path.abspath(detail_docx),
                os.path.abspath(receipt_docx),
                presc_receipt_dir,
            ))

        # === 處方執行費 ===
        if doc_data.execution_fee > 0:
            total_docx = os.path.join(exec_total_dir, f"{name}_核銷總表.docx")
            doc = create_document()
            _add_execution_fee_page(doc, data, doc_data)
            doc.save(total_docx)

            detail_docx = os.path.join(exec_detail_dir, f"{name}_民眾明細.docx")
            doc = create_document(landscape=False)
            for section in doc.sections:
                section.left_margin = Cm(1.5)
                section.right_margin = Cm(1.5)
            _add_doctor_patient_list_page(doc, data, doc_data, fee_label="處方執行費")
            doc.save(detail_docx)

            receipt = replace(base_receipt, amount=doc_data.execution_fee)
            receipt_docx = os.path.join(exec_receipt_dir, f"{name}_處方執行費領據.docx")
            generate_receipt(receipt, data.report_year, data.report_month,
                             receipt_docx,
                             fee_type="運動、營養、社會、情緒調適處方處方執行費")

            docx_info.append((
                "exec", name,
                os.path.abspath(total_docx),
                os.path.abspath(detail_docx),
                os.path.abspath(receipt_docx),
                exec_receipt_dir,
            ))

    if not also_pdf or not docx_info:
        return docx_info

    # === 批次轉 PDF（共用 Word session，每 50 份重啟一次）===
    all_docx = []
    for _, _, t, d, r, _ in docx_info:
        all_docx.extend([t, d, r])
    if progress_cb:
        progress_cb(f"開始轉換 {len(all_docx)} 份 Word → PDF")
    def _log_progress(done, total, name):
        if progress_cb and (done % 10 == 0 or done == total):
            progress_cb(f"  [{done}/{total}] 已轉換 {name}")
    _convert_docx_list_to_pdf(all_docx, progress_cb=_log_progress)

    # === 每位醫師合併 3 份 PDF 成一份 (PDF/{醫師}.pdf) ===
    merge_doctor_receipt_pdfs(docx_info, progress_cb)

    return docx_info


def merge_doctor_receipt_pdfs(docx_info, progress_cb=None):
    """合併醫師處方費/處方執行費的 3 份 PDF（總表+明細+領據）"""
    try:
        from PyPDF2 import PdfMerger
    except ImportError:
        return

    if progress_cb:
        progress_cb("合併 PDF...")
    for kind, name, total_docx, detail_docx, receipt_docx, receipt_dir in docx_info:
        pdfs = [
            total_docx.replace(".docx", ".pdf"),
            detail_docx.replace(".docx", ".pdf"),
            receipt_docx.replace(".docx", ".pdf"),
        ]
        if not all(os.path.exists(p) for p in pdfs):
            continue

        pdf_dir = os.path.join(receipt_dir, "PDF")
        os.makedirs(pdf_dir, exist_ok=True)
        final_pdf = os.path.join(pdf_dir, f"{name}.pdf")
        try:
            merger = PdfMerger()
            for p in pdfs:
                merger.append(p)
            merger.write(final_pdf)
            merger.close()
        except Exception as e:
            if progress_cb:
                progress_cb(f"  [WARN] {name} {kind} PDF 合併失敗: {e}")


def generate_health_mgmt_individual_docs(data: AllData,
                                          month_dir: str,
                                          receipt_lookup: dict | None = None,
                                          also_pdf: bool = True,
                                          progress_cb=None):
    """每間診所（clinic_person）產生 核銷總表 / 民眾明細 / 領據 個別 docx + 合併 PDF

    資料夾結構（month_dir 下）：
      健康管理費核銷總表/{clinic_person}_核銷總表.docx + .pdf
      健康管理費民眾明細/{clinic_person}_民眾明細.docx + .pdf
      健康管理費領據/{clinic_person}_領據.docx + .pdf
      健康管理費領據/PDF/{clinic_person}.pdf  (3 份合併)
    """
    from templates.receipt import generate_receipt
    from templates.clinic import _add_health_mgmt_page, HEALTH_MGMT_FEE
    from dataclasses import replace

    total_dir   = os.path.join(month_dir, "健康管理費核銷總表")
    detail_dir  = os.path.join(month_dir, "健康管理費民眾明細")
    receipt_dir = os.path.join(month_dir, "健康管理費領據")
    for d in [total_dir, detail_dir, receipt_dir]:
        os.makedirs(d, exist_ok=True)

    def _find_clinic_person(clinic_name: str):
        """在 receipt_lookup 裡找 所屬診所(clinic_name) 匹配的人
        優先順序：醫師 > 其他角色
        比對方式：精確 → 子字串雙向 → 最長共同前綴 ≥3
        回傳 (person_name, ReceiptInfo) 或 (None, None)
        """
        if not receipt_lookup or not clinic_name:
            return None, None

        def _matches(cn):
            """cn 是否匹配 clinic_name"""
            if not cn:
                return False
            if cn == clinic_name or clinic_name == cn:
                return True
            if cn in clinic_name or clinic_name in cn:
                return True
            # 最長共同前綴 ≥3
            n = 0
            for a, b in zip(clinic_name, cn):
                if a == b:
                    n += 1
                else:
                    break
            return n >= 3

        # 收集所有匹配的人
        matches = []
        for pname, info in receipt_lookup.items():
            if _matches(info.clinic_name):
                matches.append((pname, info))

        if not matches:
            return None, None

        # 優先選 醫師，再選其他
        ROLE_PRIORITY = {"醫師": 0}
        matches.sort(key=lambda x: ROLE_PRIORITY.get(x[1].role, 99))
        return matches[0]

    docx_info = []  # (name, total_docx, detail_docx, receipt_docx)

    for hm in data.health_mgmts:
        amount = HEALTH_MGMT_FEE if hm.is_qualified else 0
        if amount <= 0:
            continue

        # 決定領據具領人：
        # (1) 用 receipt_lookup 的「所屬診所」匹配（醫師優先）
        # (2) 退回用 hm.clinic_person
        # (3) 最後才用 medical_institution
        matched_name, matched_info = _find_clinic_person(hm.medical_institution)
        if matched_name:
            person = matched_name
            prev = matched_info
        elif hm.clinic_person and receipt_lookup and hm.clinic_person in receipt_lookup:
            person = hm.clinic_person
            prev = receipt_lookup[person]
        else:
            person = hm.clinic_person or hm.medical_institution
            prev = receipt_lookup.get(person) if receipt_lookup else None

        if not person:
            continue

        # 領據個資帶入
        base_receipt = ReceiptInfo(recipient_name=person, amount=amount)
        if prev is not None:
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

        # 核銷總表（單頁，橫向 — 配合 clinic.py 現有欄寬設計）
        total_docx = os.path.join(total_dir, f"{person}_核銷總表.docx")
        doc = create_document()
        _add_health_mgmt_page(doc, data, hm, min_prescriptions=data.min_prescriptions)
        doc.save(total_docx)

        # 民眾明細（直式 + 縮邊距）
        detail_docx = os.path.join(detail_dir, f"{person}_民眾明細.docx")
        doc = create_document(landscape=False)
        for section in doc.sections:
            section.left_margin = Cm(1.5)
            section.right_margin = Cm(1.5)
        _add_clinic_patient_list_page(doc, data, hm)
        doc.save(detail_docx)

        # 領據
        receipt_docx = os.path.join(receipt_dir, f"{person}_領據.docx")
        generate_receipt(base_receipt, data.report_year, data.report_month,
                         receipt_docx, fee_type="健康管理費")

        docx_info.append((
            person,
            os.path.abspath(total_docx),
            os.path.abspath(detail_docx),
            os.path.abspath(receipt_docx),
        ))

    if not also_pdf or not docx_info:
        return docx_info, receipt_dir

    # 批次轉 PDF
    all_docx = []
    for _, t, d, r in docx_info:
        all_docx.extend([t, d, r])
    if progress_cb:
        progress_cb(f"開始轉換健康管理費 {len(all_docx)} 份 Word → PDF")
    def _log_p(done, total, name):
        if progress_cb and (done % 10 == 0 or done == total):
            progress_cb(f"  [{done}/{total}] {name}")
    _convert_docx_list_to_pdf(all_docx, progress_cb=_log_p)

    # 合併 PDF
    merge_health_mgmt_pdfs(docx_info, receipt_dir, progress_cb)

    return docx_info, receipt_dir


def merge_health_mgmt_pdfs(docx_info, receipt_dir, progress_cb=None):
    """合併健康管理費的 3 份 PDF（總表+明細+領據）"""
    try:
        from PyPDF2 import PdfMerger
    except ImportError:
        return

    for person, total_docx, detail_docx, receipt_docx in docx_info:
        pdfs = [
            total_docx.replace(".docx", ".pdf"),
            detail_docx.replace(".docx", ".pdf"),
            receipt_docx.replace(".docx", ".pdf"),
        ]
        if not all(os.path.exists(p) for p in pdfs):
            continue

        pdf_dir = os.path.join(receipt_dir, "PDF")
        os.makedirs(pdf_dir, exist_ok=True)
        final_pdf = os.path.join(pdf_dir, f"{person}.pdf")
        try:
            merger = PdfMerger()
            for p in pdfs:
                merger.append(p)
            merger.write(final_pdf)
            merger.close()
        except Exception as e:
            if progress_cb:
                progress_cb(f"  [WARN] {person} 健康管理費 PDF 合併失敗: {e}")


def _add_clinic_patient_list_page(doc, data: AllData, hm):
    """診所的民眾明細頁（直式，仿照 _add_doctor_patient_list_page）"""
    patients = hm.patients
    num = len(patients)
    prefix = f"{data.report_year}年{data.report_month:02d}月"

    add_title(doc, "台北市醫師公會健康台灣深耕計畫", size=16)
    add_title(doc, "臺北市慢性病防治全人健康智慧整合照護計畫", size=16)
    add_title(doc, f"健康管理費民眾明細表-{hm.clinic_person or hm.medical_institution}",
              size=16)

    p = doc.add_paragraph(); compact_paragraph(p)
    info_total = sum(PATIENT_COL_WIDTHS)
    add_info_table(doc, [
        ("醫療機構", hm.medical_institution),
        ("診所人員", hm.clinic_person),
        ("申報期間", f"{data.report_year}年{data.report_month}月"),
    ], col_widths=[info_total // 4, info_total * 3 // 4], font_size=12)
    p = doc.add_paragraph(); compact_paragraph(p)

    num_rows = max(num, 8) + 1
    table = doc.add_table(rows=num_rows, cols=6)
    set_table_borders(table)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_col_widths(table, PATIENT_COL_WIDTHS)

    fs = 12
    headers = ["序號", "民眾姓名", "出生日期",
               "處方類型", "處方人員", "開立日期"]
    for i, h in enumerate(headers):
        set_cell_text(table.cell(0, i), h, bold=True, font_size=fs)

    for i, pat in enumerate(patients):
        set_cell_text(table.cell(i + 1, 0), str(i + 1), font_size=fs)
        set_cell_text(table.cell(i + 1, 1), pat.name, font_size=fs)
        set_cell_text(table.cell(i + 1, 2), pat.birth_date, font_size=fs)
        set_cell_text(table.cell(i + 1, 3), pat.prescription_type, font_size=fs)
        set_cell_text(table.cell(i + 1, 4), pat.prescriber, font_size=fs)
        set_cell_text(table.cell(i + 1, 5), str(pat.exec_date or ""), font_size=fs)

    p_elem = doc.add_paragraph()
    p_elem.alignment = WD_ALIGN_PARAGRAPH.LEFT
    compact_paragraph(p_elem)
    add_run(p_elem, f"總開立份數：{num} 筆", size=12, bold=True)

    from templates.clinic import HEALTH_MGMT_FEE
    amount = HEALTH_MGMT_FEE if hm.is_qualified else 0
    p_elem = doc.add_paragraph()
    p_elem.alignment = WD_ALIGN_PARAGRAPH.LEFT
    compact_paragraph(p_elem)
    add_run(
        p_elem,
        f"{prefix}健康管理費申報金額（元）：{amount:,}",
        size=12, bold=True,
    )


def _add_doctor_patient_list_page(doc, data: AllData,
                                   doctor, fee_label: str = "處方費"):
    """為醫師產生民眾明細頁（單頁，仿照執行人員版）"""
    # 執行費明細：只列「當月有執行」的民眾
    # 處方費明細：列「當月開立」的民眾
    if "執行" in fee_label and getattr(doctor, "execution_patients", None):
        patients = doctor.execution_patients
    else:
        patients = doctor.patients
    num = len(patients)
    prefix = f"{data.report_year}年{data.report_month:02d}月"

    add_title(doc, "台北市醫師公會健康台灣深耕計畫", size=16)
    add_title(doc, "臺北市慢性病防治全人健康智慧整合照護計畫", size=16)
    add_title(doc, f"{fee_label}民眾明細表-{doctor.doctor_name}", size=16)

    # 上下兩個表格對齊：共用 PATIENT_COL_WIDTHS 的總寬，都靠左對齊
    p = doc.add_paragraph(); compact_paragraph(p)
    info_total = sum(PATIENT_COL_WIDTHS)
    add_info_table(doc, [
        ("醫療機構", doctor.medical_institution),
        ("開立醫師", doctor.doctor_name),
        ("申報期間", f"{data.report_year}年{data.report_month}月"),
    ], col_widths=[info_total // 4, info_total * 3 // 4], font_size=12)
    p = doc.add_paragraph(); compact_paragraph(p)

    num_rows = max(num, 8) + 1
    table = doc.add_table(rows=num_rows, cols=6)
    set_table_borders(table)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_col_widths(table, PATIENT_COL_WIDTHS)

    fs = 12
    headers = ["序號", "民眾姓名", "出生日期",
               "處方類型", "處方人員", "執行日期"]
    for i, h in enumerate(headers):
        set_cell_text(table.cell(0, i), h, bold=True, font_size=fs)

    for i, pat in enumerate(patients):
        set_cell_text(table.cell(i + 1, 0), str(i + 1), font_size=fs)
        set_cell_text(table.cell(i + 1, 1), pat.name, font_size=fs)
        set_cell_text(table.cell(i + 1, 2), pat.birth_date, font_size=fs)
        set_cell_text(table.cell(i + 1, 3), pat.prescription_type, font_size=fs)
        set_cell_text(table.cell(i + 1, 4), doctor.doctor_name, font_size=fs)
        set_cell_text(table.cell(i + 1, 5), str(pat.exec_date or ""), font_size=fs)

    p_elem = doc.add_paragraph()
    p_elem.alignment = WD_ALIGN_PARAGRAPH.LEFT
    compact_paragraph(p_elem)
    add_run(p_elem, f"總開立份數：{num} 筆", size=12, bold=True)

    amount = (doctor.prescription_fee if fee_label == "處方費"
              else doctor.execution_fee)
    p_elem = doc.add_paragraph()
    p_elem.alignment = WD_ALIGN_PARAGRAPH.LEFT
    compact_paragraph(p_elem)
    add_run(
        p_elem,
        f"{prefix}{fee_label}申報金額（元）：{amount:,}",
        size=12, bold=True,
    )


def _convert_docx_list_to_pdf(docx_paths: list, progress_cb=None, batch_size: int = 50):
    """將多份 docx 各自轉成獨立 PDF（不合併）

    為防止 Word 累積記憶體/處於不穩定狀態造成卡死，每 batch_size 份重啟 Word 一次。
    progress_cb(done, total, current_filename)：可選進度回呼
    """
    try:
        import win32com.client
    except ImportError:
        return

    total = len(docx_paths)
    if total == 0:
        return

    def _new_word():
        # DispatchEx 強制建立獨立的 Word process（不共用現有 instance），
        # 避免 "Property 'Word.Application.Visible' can not be set" 這種
        # Word 處於不穩定狀態時的 COM 錯誤。
        last_err = None
        for attempt in range(3):
            try:
                w = win32com.client.DispatchEx("Word.Application")
                # 設 Visible / DisplayAlerts 都可能在奇怪狀態下失敗，包 try/except
                try:
                    w.Visible = False
                except Exception:
                    pass
                try:
                    w.DisplayAlerts = 0  # wdAlertsNone
                except Exception:
                    pass
                return w
            except Exception as e:
                last_err = e
                import time
                time.sleep(1)  # 短暫等待後重試
        raise last_err if last_err else RuntimeError("無法啟動 Word")

    word = _new_word()
    try:
        for idx, docx_path in enumerate(docx_paths):
            pdf_path = docx_path.replace(".docx", ".pdf")
            try:
                wdoc = word.Documents.Open(os.path.abspath(docx_path))
                wdoc.SaveAs(os.path.abspath(pdf_path), FileFormat=17)
                wdoc.Close(SaveChanges=0)
            except Exception as e:
                if progress_cb:
                    try:
                        progress_cb(idx + 1, total, f"[WARN] {os.path.basename(docx_path)}: {e}")
                    except Exception:
                        pass
                continue

            if progress_cb:
                try:
                    progress_cb(idx + 1, total, os.path.basename(docx_path))
                except Exception:
                    pass

            # 每 batch_size 份重啟 Word（避免長 session 卡死）
            if (idx + 1) % batch_size == 0 and (idx + 1) < total:
                try:
                    word.Quit()
                except Exception:
                    pass
                word = _new_word()
    finally:
        try:
            word.Quit()
        except Exception:
            pass


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
            out_path, fee_type=executor.prescription_type + "處方處置費",
        )


def generate_executor_merged_docs(data: AllData, month_dir: str,
                                  also_pdf: bool = True,
                                  receipt_lookup: dict | None = None):
    """每位執行人員產生拆分的 Word（各自存在不同資料夾）+ 合併 PDF

    資料夾結構（month_dir 下）：
      處方處置費核銷總表/{姓名}_核銷總表.docx + .pdf     (個別，單頁)
      處方處置費民眾明細/{姓名}_民眾明細.docx + .pdf     (個別，單頁)
      處方處置費領據/{姓名}_領據.docx + .pdf             (個別)
      處方處置費領據/PDF/{處方類型}/{姓名}.pdf           (3 份合併：總表+明細+領據)

    receipt_lookup: {姓名: ReceiptInfo}，從舊領據讀入，自動帶入個人資料
    """
    from dataclasses import replace

    total_dir   = os.path.join(month_dir, "處方處置費核銷總表")
    detail_dir  = os.path.join(month_dir, "處方處置費民眾明細")
    receipt_dir = os.path.join(month_dir, "處方處置費領據")
    for d in [total_dir, detail_dir, receipt_dir]:
        os.makedirs(d, exist_ok=True)

    # 蒐集每人的 3 份 docx 路徑，供稍後批次轉 PDF + 合併
    docx_info = []  # (name, ptype, total_docx, detail_docx, receipt_docx)

    for executor in data.executors:
        if not executor.receipt or executor.receipt.amount <= 0:
            continue

        name = executor.executor_name
        ptype = executor.prescription_type

        # 若有舊領據查找表，將個人資料帶入（保留本月金額）
        receipt = executor.receipt
        if receipt_lookup and name in receipt_lookup:
            prev = receipt_lookup[name]
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

        # === 核銷總表（單頁，直式，縮小邊距）===
        total_docx = os.path.join(total_dir, f"{name}_核銷總表.docx")
        doc = create_document(landscape=False)
        for section in doc.sections:
            section.left_margin = Cm(1.5)
            section.right_margin = Cm(1.5)
        _add_treatment_fee_page(doc, data, executor)
        doc.save(total_docx)

        # === 民眾明細表（單頁，直式，縮小邊距）===
        detail_docx = os.path.join(detail_dir, f"{name}_民眾明細.docx")
        doc = create_document(landscape=False)
        for section in doc.sections:
            section.left_margin = Cm(1.5)
            section.right_margin = Cm(1.5)
        _add_patient_list_page(doc, data, executor)
        doc.save(detail_docx)

        # === 領據（直式，用模板）===
        receipt_docx = os.path.join(receipt_dir, f"{name}_領據.docx")
        # fee_type 命名慣例：{類型處方} + {費用名}，例如
        #   處方費：    "運動、營養、社會、情緒調適處方" + "處方費"       = "...處方處方費"
        #   處方執行費："運動、營養、社會、情緒調適處方" + "處方執行費"   = "...處方處方執行費"
        #   處方處置費：執行人員只單一類型，例「社會處方」+ "處方處置費" = "社會處方處方處置費"
        generate_receipt(
            receipt, data.report_year, data.report_month,
            receipt_docx, fee_type=executor.prescription_type + "處方處置費",
        )

        docx_info.append((name, ptype,
                         os.path.abspath(total_docx),
                         os.path.abspath(detail_docx),
                         os.path.abspath(receipt_docx)))

    if not also_pdf or not docx_info:
        return docx_info, receipt_dir

    # === 批次轉 PDF（同一個 Word session）===
    all_docx = []
    for _, _, t, d, r in docx_info:
        all_docx.extend([t, d, r])
    _convert_docx_list_to_pdf(all_docx)

    # === 每人合併 3 份 PDF 成一份 (PDF/{ptype}/{name}.pdf) ===
    merge_executor_pdfs(docx_info, receipt_dir)

    return docx_info, receipt_dir


def merge_executor_pdfs(docx_info, receipt_dir):
    """合併處方處置費的 3 份 PDF（總表+明細+領據）"""
    try:
        from PyPDF2 import PdfMerger
    except ImportError:
        return

    for name, ptype, total_docx, detail_docx, receipt_docx in docx_info:
        pdfs = [
            total_docx.replace(".docx", ".pdf"),
            detail_docx.replace(".docx", ".pdf"),
            receipt_docx.replace(".docx", ".pdf"),
        ]
        if not all(os.path.exists(p) for p in pdfs):
            continue

        pdf_dir = os.path.join(receipt_dir, "PDF", ptype)
        os.makedirs(pdf_dir, exist_ok=True)
        final_pdf = os.path.join(pdf_dir, f"{name}.pdf")
        try:
            merger = PdfMerger()
            for p in pdfs:
                merger.append(p)
            merger.write(final_pdf)
            merger.close()
        except Exception as e:
            print(f"  [WARN] {name} 處方處置費 PDF 合併失敗: {e}")


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

