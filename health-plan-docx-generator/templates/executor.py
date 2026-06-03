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
from config import FEE_PER_TREATMENT, FEE_PER_PRESCRIPTION, FEE_PER_EXECUTION
# 直式 A4 邊距 1.5cm，可用寬度約 18cm ≈ 6,480,000 EMU
DATA_COL_WIDTHS = [950000, 2100000, 1400000, 1750000]
PATIENT_COL_WIDTHS = [550000, 950000, 1200000, 1500000, 1100000, 1180000]

# 處方類型固定排序與 短稱
PTYPE_ORDER = ["運動處方", "營養處方", "情緒調適處方", "社會處方"]
PTYPE_SHORT = {"運動處方": "運動", "營養處方": "營養",
               "情緒調適處方": "情緒調適", "社會處方": "社會"}


def _cell_grid(table):
    """回傳快速取格函式 at(row, col)。

    python-docx 的 table.cell(r,c) 每次呼叫都會重建整張表的儲存格清單，
    在大表（如上百列的民眾明細）逐格呼叫會變成 O(n²)，CPU 燒滿近似當機。
    這裡只建一次 table._cells，之後以索引存取（與 table.cell 結果相同）。
    """
    cells = table._cells
    ncol = table._column_count
    return lambda r, c: cells[r * ncol + c]


def _write_unencrypted_list(unencrypted_by_dir: dict):
    """將每個 receipt 資料夾的未加密(身分證空白)名單寫成 未加密清單.txt。"""
    for receipt_dir, names in unencrypted_by_dir.items():
        if not names:
            continue
        try:
            os.makedirs(receipt_dir, exist_ok=True)
            txt_path = os.path.join(receipt_dir, "未加密清單.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("以下人員因身分證字號空白，PDF 未加密：\n")
                for n in names:
                    f.write(f"- {n}\n")
        except OSError:
            pass


def _present_types(executor: ExecutorData) -> list[str]:
    """回傳此執行人員實際有的處方類型,按固定順序。"""
    counts = executor.type_counts or {}
    if counts:
        return [pt for pt in PTYPE_ORDER if counts.get(pt, 0) > 0]
    if executor.prescription_type:
        return [executor.prescription_type]
    return []


def _build_executor_fee_type(executor: ExecutorData) -> str:
    """組出領據「茲收到 …」要塞的費用描述。

    單類型:  運動處方 + 處方處置費 = 運動處方處方處置費
    多類型:  運動、情緒調適、社會 + 處方處方處置費 = 運動、情緒調適、社會處方處方處置費
    """
    types = _present_types(executor)
    if len(types) <= 1:
        single = types[0] if types else executor.prescription_type
        return f"{single}處方處置費"
    parts = [PTYPE_SHORT.get(t, t) for t in types]
    return "、".join(parts) + "處方處方處置費"


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
                             progress_cb=None,
                             emit_presc_detail: bool = True,
                             emit_exec_detail: bool = True,
                             emit_receipt: bool = True):
    """每位醫師產生拆分的 Word（各自存在不同資料夾）+ 合併 PDF

    資料夾結構（month_dir 下）：
      處方處方費民眾明細/{醫師}_民眾明細.docx           ← emit_presc_detail
      處方執行費民眾明細/{醫師}_民眾明細.docx           ← emit_exec_detail
      處方處方費與處方執行費領據/{醫師}_領據.docx       ← emit_receipt
    """
    from templates.receipt import generate_receipt
    from dataclasses import replace

    # 子資料夾(只在對應 emit_* 為 True 時才建立)
    presc_detail_dir  = os.path.join(month_dir, "處方處方費民眾明細")
    exec_detail_dir   = os.path.join(month_dir, "處方執行費民眾明細")
    receipt_dir       = os.path.join(month_dir, "處方處方費與處方執行費領據")
    if emit_presc_detail:
        os.makedirs(presc_detail_dir, exist_ok=True)
    if emit_exec_detail:
        os.makedirs(exec_detail_dir, exist_ok=True)
    if emit_receipt:
        os.makedirs(receipt_dir, exist_ok=True)

    # 蒐集每位醫師的 docx 路徑（kind: "presc" / "exec"）
    # list of (kind, name, detail_docx, receipt_docx, receipt_dir, id_number)
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
                occupation=prev.occupation,
            )

        has_presc = doc_data.prescription_fee > 0
        has_exec = doc_data.execution_fee > 0

        # === 合併領據(處方費 + 執行費)— 1 份 per 醫師 ===
        merged_receipt_docx = None
        if emit_receipt and (has_presc or has_exec):
            total_amount = doc_data.prescription_fee + doc_data.execution_fee
            receipt = replace(base_receipt, amount=total_amount)
            merged_receipt_docx = os.path.join(
                receipt_dir, f"{name}_領據.docx")
            generate_receipt(
                receipt, data.report_year, data.report_month,
                merged_receipt_docx,
                fee_type="運動、營養、情緒調適、社會處方處方費與處方執行費",
                presc_counts={
                    "運動處方":     doc_data.exercise,
                    "營養處方":     doc_data.nutrition,
                    "社會處方":     doc_data.social,
                    "情緒調適處方": doc_data.emotion,
                },
                exec_counts={
                    "運動處方":     doc_data.exercise_exec,
                    "營養處方":     doc_data.nutrition_exec,
                    "社會處方":     doc_data.social_exec,
                    "情緒調適處方": doc_data.emotion_exec,
                },
                fee_per_presc=FEE_PER_PRESCRIPTION,
                fee_per_exec=FEE_PER_EXECUTION,
            )

        # === 處方費民眾明細 ===
        if emit_presc_detail and has_presc:
            detail_docx = os.path.join(presc_detail_dir, f"{name}_民眾明細.docx")
            doc = create_document(landscape=False)
            for section in doc.sections:
                section.left_margin = Cm(1.5)
                section.right_margin = Cm(1.5)
                section.top_margin = Cm(1.5)
                section.bottom_margin = Cm(1.5)
            _add_doctor_patient_list_page(doc, data, doc_data, fee_label="處方費")
            doc.save(detail_docx)

            docx_info.append((
                "presc", name,
                os.path.abspath(detail_docx),
                os.path.abspath(merged_receipt_docx) if merged_receipt_docx else None,
                receipt_dir,
                base_receipt.id_number,
            ))

        # === 處方執行費民眾明細 ===
        if emit_exec_detail and has_exec:
            detail_docx = os.path.join(exec_detail_dir, f"{name}_民眾明細.docx")
            doc = create_document(landscape=False)
            for section in doc.sections:
                section.left_margin = Cm(1.5)
                section.right_margin = Cm(1.5)
                section.top_margin = Cm(1.5)
                section.bottom_margin = Cm(1.5)
            _add_doctor_patient_list_page(doc, data, doc_data, fee_label="處方執行費")
            doc.save(detail_docx)

            docx_info.append((
                "exec", name,
                os.path.abspath(detail_docx),
                os.path.abspath(merged_receipt_docx) if merged_receipt_docx else None,
                receipt_dir,
                base_receipt.id_number,
            ))

        # 若三種子類別都不產但仍要記錄領據(讓 PDF 合併能找到),
        # 加一個僅含領據的紀錄
        if emit_receipt and merged_receipt_docx and not has_presc and not has_exec:
            docx_info.append((
                "receipt_only", name, None,
                os.path.abspath(merged_receipt_docx),
                receipt_dir,
                base_receipt.id_number,
            ))
        elif emit_receipt and merged_receipt_docx \
                and not emit_presc_detail and not emit_exec_detail:
            # 只勾領據,沒勾任何明細 — 讓 docx_info 至少有一筆
            if not any(n == name for _, n, _, _, _, _ in docx_info):
                docx_info.append((
                    "receipt_only", name, None,
                    os.path.abspath(merged_receipt_docx),
                    receipt_dir,
                    base_receipt.id_number,
                ))

    if not also_pdf or not docx_info:
        return docx_info

    # === 批次轉 PDF（明細 + 領據；不再合併 PDF）===
    # 領據是 處方費 / 執行費 兩 docx_info 共用，去重避免重複轉換
    all_docx = []
    seen = set()
    for _, _, d, r, _, _ in docx_info:
        for path in (d, r):
            if path and path not in seen:
                all_docx.append(path)
                seen.add(path)
    if progress_cb:
        progress_cb(f"開始轉換 {len(all_docx)} 份 Word → PDF")
    def _log_progress(done, total, name):
        if progress_cb and (done % 10 == 0 or done == total):
            progress_cb(f"  [{done}/{total}] 已轉換 {name}")
    _convert_docx_list_to_pdf(all_docx, progress_cb=_log_progress)

    return docx_info


def merge_doctor_receipt_pdfs(docx_info, master_password=None, progress_cb=None):
    """合併醫師「明細(處方費+執行費可能各一) + 領據」每人 1 份 PDF。
    docx_info tuple: (kind, name, detail_docx, receipt_docx, receipt_dir, id_number)
    身分證字號當 user_password；master_password 當 owner_password
    （兩者皆可開啟 PDF）。身分證空白 → 不加密，並列入 未加密清單.txt。
    """
    try:
        from pdf_merge import merge_pdfs_encrypted, normalize_id_number
    except ImportError:
        return

    if progress_cb:
        progress_cb("合併 明細+領據 PDF...")

    # 把同醫師的 entries 收成一組
    by_doctor = {}
    for kind, name, detail_docx, receipt_docx, receipt_dir, id_number in docx_info:
        bucket = by_doctor.setdefault(name, {
            "presc_detail": None, "exec_detail": None,
            "receipt": receipt_docx, "receipt_dir": receipt_dir,
            "id_number": id_number,
        })
        if kind == "presc":
            bucket["presc_detail"] = detail_docx
        elif kind == "exec":
            bucket["exec_detail"] = detail_docx
        if not bucket.get("id_number") and id_number:
            bucket["id_number"] = id_number

    unencrypted_by_dir: dict[str, list[str]] = {}

    for name, b in by_doctor.items():
        ordered = []
        for key in ("presc_detail", "exec_detail", "receipt"):
            p = b.get(key)
            if not p:
                continue
            pdf = p.replace(".docx", ".pdf")
            if os.path.exists(pdf) and pdf not in ordered:
                ordered.append(pdf)
        if not ordered:
            continue
        receipt_dir = b["receipt_dir"]
        final_pdf = os.path.join(receipt_dir, f"{name}_明細領據.pdf")
        user_pw = normalize_id_number(b.get("id_number"))
        try:
            merge_pdfs_encrypted(
                ordered, final_pdf,
                user_password=user_pw or None,
                owner_password=master_password or None,
            )
            if not user_pw:
                unencrypted_by_dir.setdefault(receipt_dir, []).append(name)
        except Exception as e:
            if progress_cb:
                progress_cb(f"  [WARN] {name} PDF 合併失敗: {e}")

    _write_unencrypted_list(unencrypted_by_dir)


def generate_health_mgmt_individual_docs(data: AllData,
                                          month_dir: str,
                                          receipt_lookup: dict | None = None,
                                          also_pdf: bool = True,
                                          progress_cb=None,
                                          emit_detail: bool = True,
                                          emit_receipt: bool = True):
    """每間診所(clinic_person)產生 民眾明細 / 領據 個別 docx + 合併 PDF

    資料夾結構(month_dir 下):
      健康管理費民眾明細/{clinic_person}_民眾明細.docx     ← emit_detail
      健康管理費領據/{clinic_person}_領據.docx             ← emit_receipt
    """
    from templates.receipt import generate_receipt
    from templates.clinic import _add_health_mgmt_page, HEALTH_MGMT_FEE
    from dataclasses import replace

    detail_dir  = os.path.join(month_dir, "健康管理費民眾明細")
    receipt_dir = os.path.join(month_dir, "健康管理費領據")
    if emit_detail:
        os.makedirs(detail_dir, exist_ok=True)
    if emit_receipt:
        os.makedirs(receipt_dir, exist_ok=True)

    def _find_clinic_person(clinic_name: str):
        return find_clinic_admin(receipt_lookup, clinic_name)

    docx_info = []  # (name, total_docx, detail_docx, receipt_docx)

    for hm in data.health_mgmts:
        amount = HEALTH_MGMT_FEE if hm.is_qualified else 0
        if amount <= 0:
            continue

        # 決定領據具領人：
        # 個資 Excel 有對應這家診所的列 → 用該列姓名（可能是空白）
        # 個資 Excel 完全沒對應 → 姓名留空白（不再 fallback 用醫師名）
        recipient_name, prev = _find_clinic_person(hm.medical_institution)
        # 檔名用具領人；若空就用診所名（避免檔名為「_領據.docx」）
        person = recipient_name or hm.medical_institution

        # 領據個資帶入
        # 領據具領人：用個資 Excel 找到的姓名（找不到則空白）
        # ─ person 變數只用於檔名 / 訊息，不會寫進領據
        base_receipt = ReceiptInfo(recipient_name=recipient_name, amount=amount)
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
                occupation=prev.occupation,
            )

        # 民眾明細(直式 + 縮邊距)
        detail_docx = None
        if emit_detail:
            detail_docx = os.path.join(detail_dir, f"{person}_民眾明細.docx")
            doc = create_document(landscape=False)
            for section in doc.sections:
                section.left_margin = Cm(1.5)
                section.right_margin = Cm(1.5)
                section.top_margin = Cm(1.5)
                section.bottom_margin = Cm(1.5)
            _add_clinic_patient_list_page(doc, data, hm)
            doc.save(detail_docx)

        # 領據
        receipt_docx = None
        if emit_receipt:
            receipt_docx = os.path.join(receipt_dir, f"{person}_領據.docx")
            generate_receipt(
                base_receipt, data.report_year, data.report_month,
                receipt_docx, fee_type="健康管理費",
                people_count=hm.prescription_people,
                prescription_count=hm.prescription_count,
                is_qualified=hm.is_qualified,
            )

        if detail_docx or receipt_docx:
            docx_info.append((
                person,
                os.path.abspath(detail_docx) if detail_docx else None,
                os.path.abspath(receipt_docx) if receipt_docx else None,
                base_receipt.id_number,
            ))

    if not also_pdf or not docx_info:
        return docx_info, receipt_dir

    # 批次轉 PDF(明細 + 領據;不再合併 PDF)
    all_docx = []
    for _, d, r, _ in docx_info:
        for p in (d, r):
            if p:
                all_docx.append(p)
    if progress_cb:
        progress_cb(f"開始轉換健康管理費 {len(all_docx)} 份 Word → PDF")
    def _log_p(done, total, name):
        if progress_cb and (done % 10 == 0 or done == total):
            progress_cb(f"  [{done}/{total}] {name}")
    _convert_docx_list_to_pdf(all_docx, progress_cb=_log_p)

    return docx_info, receipt_dir


def merge_health_mgmt_pdfs(docx_info, receipt_dir, master_password=None, progress_cb=None):
    """合併健康管理費「明細 + 領據」每人 1 份 PDF。
    docx_info tuple: (person, detail_docx, receipt_docx, id_number)
    身分證字號當 user_password；master_password 當 owner_password。
    身分證空白 → 不加密，並列入 未加密清單.txt。
    """
    try:
        from pdf_merge import merge_pdfs_encrypted, normalize_id_number
    except ImportError:
        return

    unencrypted_names: list[str] = []

    for person, detail_docx, receipt_docx, id_number in docx_info:
        # 兩者可能其中之一為 None(該項未勾選產出)
        if not detail_docx or not receipt_docx:
            continue
        pdfs = [
            detail_docx.replace(".docx", ".pdf"),
            receipt_docx.replace(".docx", ".pdf"),
        ]
        if not all(os.path.exists(p) for p in pdfs):
            continue

        final_pdf = os.path.join(receipt_dir, f"{person}_明細領據.pdf")
        user_pw = normalize_id_number(id_number)
        try:
            merge_pdfs_encrypted(
                pdfs, final_pdf,
                user_password=user_pw or None,
                owner_password=master_password or None,
            )
            if not user_pw:
                unencrypted_names.append(person)
        except Exception as e:
            if progress_cb:
                progress_cb(f"  [WARN] {person} 健康管理費 PDF 合併失敗: {e}")

    if unencrypted_names:
        _write_unencrypted_list({receipt_dir: unencrypted_names})


def find_clinic_admin(receipt_lookup: dict | None, clinic_name: str):
    """在 receipt_lookup 裡找 所屬診所(clinic_name) 匹配的「診所行政人員」。

    健管費領據的具領人應該是診所行政人員,絕不該抓到醫師資料。
    比對方式:精確 → 子字串雙向 → 最長共同前綴 ≥3
    優先有姓名的列;若全部留白(佔位列),取第一筆。
    回傳 (recipient_name, ReceiptInfo) 或 ("", None)

    供健管費領據與富邦匯款檔共用,確保具領人/帳戶來源一致。
    """
    if not receipt_lookup or not clinic_name:
        return "", None

    def _matches(cn):
        if not cn:
            return False
        if cn == clinic_name or clinic_name == cn:
            return True
        if cn in clinic_name or clinic_name in cn:
            return True
        n = 0
        for a, b in zip(clinic_name, cn):
            if a == b:
                n += 1
            else:
                break
        return n >= 3

    matches = [info for info in receipt_lookup.values()
               if info.role == "診所行政人員"
               and _matches(info.clinic_name)]
    if not matches:
        return "", None
    matches.sort(key=lambda i: 0 if i.recipient_name else 1)
    best = matches[0]
    return best.recipient_name or "", best


_PRESCRIPTION_GROUP_ORDER = ["運動處方", "營養處方", "情緒調適處方", "社會處方"]


def _group_by_prescription(patients):
    """按處方類型分組排序（運動 → 營養 → 社會 → 情緒調適），同類別內保留原順序。
    未知類型排在最後。
    """
    order_map = {pt: i for i, pt in enumerate(_PRESCRIPTION_GROUP_ORDER)}
    return sorted(patients, key=lambda p: order_map.get(
        getattr(p, "prescription_type", ""), 99))


def _add_clinic_patient_list_page(doc, data: AllData, hm):
    """診所的民眾明細頁（直式，仿照 _add_doctor_patient_list_page）"""
    patients = _group_by_prescription(hm.patients)
    num = len(patients)
    prefix = f"{data.report_year}年{data.report_month:02d}月"

    add_title(doc, "台北市醫師公會健康台灣深耕計畫", size=16)
    add_title(doc, "臺北市慢性病防治全人健康智慧整合照護計畫", size=16)
    add_title(doc, f"健康管理費民眾明細表-{hm.clinic_person}",
              size=16)

    p = doc.add_paragraph(); compact_paragraph(p)
    info_total = sum(PATIENT_COL_WIDTHS)
    add_info_table(doc, [
        ("醫療機構", hm.medical_institution),
        ("診所人員", hm.clinic_person),
        ("申報期間", f"{data.report_year}年{data.report_month}月"),
    ], col_widths=[info_total // 4, info_total * 3 // 4], font_size=12)
    p = doc.add_paragraph(); compact_paragraph(p)

    num_rows = max(num, 1) + 1
    table = doc.add_table(rows=num_rows, cols=6)
    set_table_borders(table)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_col_widths(table, PATIENT_COL_WIDTHS)

    fs = 12
    cell_at = _cell_grid(table)
    headers = ["序號", "民眾姓名", "出生日期",
               "處方類型", "行政人員", "開立日期"]
    for i, h in enumerate(headers):
        set_cell_text(cell_at(0, i), h, bold=True, font_size=fs)

    for i, pat in enumerate(patients):
        set_cell_text(cell_at(i + 1, 0), str(i + 1), font_size=fs)
        set_cell_text(cell_at(i + 1, 1), pat.name, font_size=fs)
        set_cell_text(cell_at(i + 1, 2), pat.birth_date, font_size=fs)
        set_cell_text(cell_at(i + 1, 3), pat.prescription_type, font_size=fs)
        set_cell_text(cell_at(i + 1, 4), hm.clinic_person or "", font_size=fs)
        set_cell_text(cell_at(i + 1, 5), str(pat.issue_date or ""), font_size=fs)

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
    # 執行費明細：只列「當月有執行」的民眾（即使為空也不 fallback）
    # 處方費明細：列「當月開立」的民眾
    if "執行" in fee_label:
        # 優先用 execution_patients；若屬性不存在（舊版 dataclass）才退回
        if hasattr(doctor, "execution_patients"):
            patients = doctor.execution_patients
        else:
            patients = doctor.patients
    else:
        patients = doctor.patients
    patients = _group_by_prescription(patients)
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

    num_rows = max(num, 1) + 1
    table = doc.add_table(rows=num_rows, cols=6)
    set_table_borders(table)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_col_widths(table, PATIENT_COL_WIDTHS)

    fs = 12
    # 處方費 → 顯示開立日期；處方執行費 → 顯示執行日期
    use_exec = "執行" in fee_label
    date_header = "執行日期" if use_exec else "開立日期"
    headers = ["序號", "民眾姓名", "出生日期",
               "處方類型", "處方人員", date_header]
    cell_at = _cell_grid(table)
    for i, h in enumerate(headers):
        set_cell_text(cell_at(0, i), h, bold=True, font_size=fs)

    for i, pat in enumerate(patients):
        date_val = pat.exec_date if use_exec else getattr(pat, "issue_date", "")
        set_cell_text(cell_at(i + 1, 0), str(i + 1), font_size=fs)
        set_cell_text(cell_at(i + 1, 1), pat.name, font_size=fs)
        set_cell_text(cell_at(i + 1, 2), pat.birth_date, font_size=fs)
        set_cell_text(cell_at(i + 1, 3), pat.prescription_type, font_size=fs)
        set_cell_text(cell_at(i + 1, 4), doctor.doctor_name, font_size=fs)
        set_cell_text(cell_at(i + 1, 5), str(date_val or ""), font_size=fs)

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
                occupation=receipt.occupation or prev.occupation,
            )

        from templates.receipt import generate_receipt
        out_path = os.path.join(output_dir, f"{name}_領據.docx")
        generate_receipt(
            receipt, data.report_year, data.report_month,
            out_path, fee_type=executor.prescription_type + "處方處置費",
            treatment_counts={executor.prescription_type: executor.service_count},
            fee_per_treatment=FEE_PER_TREATMENT,
        )


def generate_executor_merged_docs(data: AllData, month_dir: str,
                                  also_pdf: bool = True,
                                  receipt_lookup: dict | None = None,
                                  emit_detail: bool = True,
                                  emit_receipt: bool = True):
    """每位執行人員產生拆分的 Word(各自存在不同資料夾)+ 合併 PDF

    資料夾結構(month_dir 下):
      處方處置費民眾明細/{姓名}_民眾明細.docx     ← emit_detail
      處方處置費領據/{姓名}_領據.docx             ← emit_receipt

    receipt_lookup: {姓名: ReceiptInfo},從舊領據讀入,自動帶入個人資料
    """
    from dataclasses import replace

    detail_dir  = os.path.join(month_dir, "處方處置費民眾明細")
    receipt_dir = os.path.join(month_dir, "處方處置費領據")
    if emit_detail:
        os.makedirs(detail_dir, exist_ok=True)
    if emit_receipt:
        os.makedirs(receipt_dir, exist_ok=True)

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
                occupation=receipt.occupation or prev.occupation,
            )

        # === 民眾明細表(單頁,直式,縮小邊距) ===
        detail_docx = None
        if emit_detail:
            detail_docx = os.path.join(detail_dir, f"{name}_民眾明細.docx")
            doc = create_document(landscape=False)
            for section in doc.sections:
                section.left_margin = Cm(1.5)
                section.right_margin = Cm(1.5)
                section.top_margin = Cm(1.5)
                section.bottom_margin = Cm(1.5)
            _add_patient_list_page(doc, data, executor)
            doc.save(detail_docx)

        # === 領據(直式,用模板) ===
        # 多類型時 fee_type 列出所有類型,treatment_counts 一次帶全;
        # 模板的 4×6 pivot 表會自動依 PIVOT_COL_ORDER 填各類份數與金額。
        receipt_docx = None
        if emit_receipt:
            receipt_docx = os.path.join(receipt_dir, f"{name}_領據.docx")
            generate_receipt(
                receipt, data.report_year, data.report_month,
                receipt_docx,
                fee_type=_build_executor_fee_type(executor),
                treatment_counts=executor.type_counts or
                                 {executor.prescription_type: executor.service_count},
                fee_per_treatment=FEE_PER_TREATMENT,
            )

        if detail_docx or receipt_docx:
            docx_info.append((
                name, ptype,
                os.path.abspath(detail_docx) if detail_docx else None,
                os.path.abspath(receipt_docx) if receipt_docx else None,
                receipt.id_number))

    if not also_pdf or not docx_info:
        return docx_info, receipt_dir

    # === 批次轉 PDF(明細 + 領據;不再合併 PDF)===
    all_docx = []
    for _, _, d, r, _ in docx_info:
        for p in (d, r):
            if p:
                all_docx.append(p)
    _convert_docx_list_to_pdf(all_docx)

    return docx_info, receipt_dir


def merge_executor_pdfs(docx_info, receipt_dir, master_password=None):
    """合併處方處置費「明細 + 領據」每人 1 份 PDF。
    docx_info tuple: (name, ptype, detail_docx, receipt_docx, id_number)
    身分證字號當 user_password；master_password 當 owner_password。
    身分證空白 → 不加密，並列入 未加密清單.txt。
    """
    try:
        from pdf_merge import merge_pdfs_encrypted, normalize_id_number
    except ImportError:
        return

    # 同一姓名可能因多 ptype 出現多筆，去重避免重複加密同檔
    seen_names: set[str] = set()
    unencrypted_names: list[str] = []

    for name, ptype, detail_docx, receipt_docx, id_number in docx_info:
        if name in seen_names:
            continue
        if not detail_docx or not receipt_docx:
            continue
        pdfs = [
            detail_docx.replace(".docx", ".pdf"),
            receipt_docx.replace(".docx", ".pdf"),
        ]
        if not all(os.path.exists(p) for p in pdfs):
            continue

        final_pdf = os.path.join(receipt_dir, f"{name}_明細領據.pdf")
        user_pw = normalize_id_number(id_number)
        try:
            merge_pdfs_encrypted(
                pdfs, final_pdf,
                user_password=user_pw or None,
                owner_password=master_password or None,
            )
            seen_names.add(name)
            if not user_pw:
                unencrypted_names.append(name)
        except Exception as e:
            print(f"  [WARN] {name} 處方處置費 PDF 合併失敗: {e}")

    if unencrypted_names:
        _write_unencrypted_list({receipt_dir: unencrypted_names})


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

    types = _present_types(executor) or [executor.prescription_type or ""]
    counts = executor.type_counts or {executor.prescription_type: executor.service_count}

    # 行數: 1 標頭 + N 類型 + 1 總計
    table = doc.add_table(rows=2 + len(types), cols=4)
    set_table_borders(table)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_col_widths(table, DATA_COL_WIDTHS)

    headers = ["編號", "處方類型", "服務人次", "申報金額(元)"]
    for i, h in enumerate(headers):
        set_cell_text(table.cell(0, i), h, bold=True, font_size=14)

    grand_count = 0
    grand_amount = 0
    for r, pt in enumerate(types, start=1):
        cnt = counts.get(pt, 0)
        amt = cnt * FEE_PER_TREATMENT
        grand_count += cnt
        grand_amount += amt
        set_cell_text(table.cell(r, 0), str(r), font_size=14)
        set_cell_text(table.cell(r, 1), pt, align="left", font_size=14)
        set_cell_text(table.cell(r, 2), str(cnt), font_size=14)
        set_cell_text(table.cell(r, 3), f"${amt:,}", font_size=14)

    total_row = 1 + len(types)
    set_cell_text(table.cell(total_row, 0), "", font_size=14)
    set_cell_text(table.cell(total_row, 1), "總計", bold=True, font_size=14)
    set_cell_text(table.cell(total_row, 2), str(grand_count), bold=True, font_size=14)
    set_cell_text(table.cell(total_row, 3), f"${grand_amount:,}", bold=True, font_size=14)

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

    # 多類型時標題不冠類型,單類型則保留原本「{類型}處方處置費總表」格式
    types = _present_types(executor)
    if len(types) <= 1:
        title_prefix = executor.prescription_type
    else:
        title_prefix = ""

    # 標頭
    add_title(doc, "台北市醫師公會健康台灣深耕計畫", size=16)
    add_title(doc, "臺北市慢性病防治全人健康智慧整合照護計畫", size=16)
    add_title(doc,
              f"{title_prefix}處方處置費總表-{executor.executor_name}",
              size=16)

    # 表格 6 欄(含執行日期)
    num_rows = max(num, 1) + 1
    table = doc.add_table(rows=num_rows, cols=6)
    set_table_borders(table)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_col_widths(table, PATIENT_COL_WIDTHS)

    fs = 12  # 直式頁面 6 欄字體
    headers = ["序號", "民眾姓名", "出生日期",
               "處方類型", "處方人員", "執行日期"]
    cell_at = _cell_grid(table)
    for i, h in enumerate(headers):
        set_cell_text(cell_at(0, i), h, bold=True, font_size=fs)

    for i, p in enumerate(patients):
        # 民眾的處方類型以該筆紀錄為準(支援多類型);若空再 fallback
        row_ptype = p.prescription_type or executor.prescription_type
        set_cell_text(cell_at(i + 1, 0), str(i + 1), font_size=fs)
        set_cell_text(cell_at(i + 1, 1), p.name, font_size=fs)
        set_cell_text(cell_at(i + 1, 2), p.birth_date, font_size=fs)
        set_cell_text(cell_at(i + 1, 3), row_ptype, font_size=fs)
        set_cell_text(cell_at(i + 1, 4), executor.executor_name, font_size=fs)
        exec_date = getattr(p, "exec_date", "")
        set_cell_text(cell_at(i + 1, 5), str(exec_date), font_size=fs)

    # 底部摘要 — 靠左、粗體
    p_elem = doc.add_paragraph()
    p_elem.alignment = WD_ALIGN_PARAGRAPH.LEFT
    compact_paragraph(p_elem)
    add_run(p_elem, f"總服務人次:{num}人", size=12, bold=True)

    p_elem = doc.add_paragraph()
    p_elem.alignment = WD_ALIGN_PARAGRAPH.LEFT
    compact_paragraph(p_elem)
    add_run(
        p_elem,
        f"{prefix}{title_prefix}處方處置費總申報金額(元):{amount:,}",
        size=12, bold=True,
    )

