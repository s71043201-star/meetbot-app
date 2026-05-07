"""直接從原始 Word 模板複製格式，只替換數據。

策略：
1. 開啟用戶提供的實際 Word 檔
2. 第一位醫師的區塊作為「模板」
3. 複製模板 N 次，每次替換醫師的數據
"""

import copy
import os
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from models import AllData, DoctorPrescription
from config import FEE_PER_PRESCRIPTION, FEE_PER_EXECUTION


def _make_page_break_paragraph():
    """產生一個只含分頁符的段落 (<w:p><w:r><w:br w:type='page'/></w:r></w:p>)"""
    p = OxmlElement("w:p")
    r = OxmlElement("w:r")
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    r.append(br)
    p.append(r)
    return p


def _get_all_text_runs(element):
    """取得 element 下所有的 w:t 節點"""
    return list(element.iter(qn("w:t")))


def _get_element_text(element):
    """取得 element 的完整文字"""
    return "".join(t.text or "" for t in _get_all_text_runs(element))


def _find_section_boundaries(body_elements):
    """找出每個醫師 section 的起止 index

    每個 section 的結構：
    - 3 個 title 段落
    - 1 個空段落
    - 1 個 info table (3x2)
    - 1 個空段落
    - 1 個 data table (6x4)
    - 若干 note 段落
    - 1 個 signature 段落
    """
    sections = []
    section_start = None
    table_count_in_section = 0

    for i, elem in enumerate(body_elements):
        is_table = elem.tag == qn("w:tbl")
        is_para = elem.tag == qn("w:p")

        if is_para:
            text = _get_element_text(elem)
            if "台北市醫師公會" in text and "深耕計畫" in text:
                if section_start is not None:
                    sections.append((section_start, i - 1))
                section_start = i
                table_count_in_section = 0

        if is_table and section_start is not None:
            table_count_in_section += 1

    # Last section
    if section_start is not None:
        sections.append((section_start, len(body_elements) - 1))

    return sections


def _replace_table_cell(table_elem, row_idx, col_idx, new_text):
    """替換表格指定 cell 的文字，保留第一個 run 的格式，刪除多餘 run"""
    rows = table_elem.findall(qn("w:tr"))
    if row_idx >= len(rows):
        return
    cells = rows[row_idx].findall(qn("w:tc"))
    if col_idx >= len(cells):
        return

    cell = cells[col_idx]
    for p in cell.findall(qn("w:p")):
        runs = p.findall(qn("w:r"))
        if not runs:
            continue
        # 保留第一個 run 的格式，設定新文字
        first_run = runs[0]
        texts = first_run.findall(qn("w:t"))
        if texts:
            texts[0].text = str(new_text)
            # 刪除第一個 run 中的多餘 w:t
            for extra_t in texts[1:]:
                first_run.remove(extra_t)
        # 刪除所有多餘的 run
        for extra_run in runs[1:]:
            p.remove(extra_run)
        return


def _replace_in_paragraphs(section_elements, replacements):
    """在段落中替換文字"""
    for elem in section_elements:
        if elem.tag != qn("w:p"):
            continue
        for run in elem.iter(qn("w:r")):
            for t in run.iter(qn("w:t")):
                if t.text:
                    for old, new in replacements.items():
                        if old in t.text:
                            t.text = t.text.replace(old, new)


def generate_from_template(template_path: str, data: AllData,
                           doctors: list[DoctorPrescription],
                           doc_type: str, output_path: str):
    """用模板文件產生新的 Word 文件

    Args:
        template_path: 實際的 Word 模板路徑
        data: 所有資料
        doctors: 要產生的醫師列表
        doc_type: 'prescription' | 'execution'
        output_path: 輸出路徑
    """
    src = Document(template_path)
    src_body = src.element.body
    src_elements = [
        child for child in src_body
        if child.tag in (qn("w:p"), qn("w:tbl"))
    ]

    sections = _find_section_boundaries(src_elements)
    if not sections:
        raise ValueError("無法在模板中找到醫師區塊")

    # 取得第一個 section 作為模板
    template_start, template_end = sections[0]
    template_elements = src_elements[template_start:template_end + 1]

    # 建立新文件（保留模板的樣式和頁面設定）
    new_doc = Document(template_path)
    new_body = new_doc.element.body

    # 清除所有內容
    for child in list(new_body):
        if child.tag in (qn("w:p"), qn("w:tbl")):
            new_body.remove(child)

    # 為每位醫師產生一個 section
    for i, doctor in enumerate(doctors):
        # 第二位醫師起，先插入分頁符
        if i > 0:
            new_body.append(_make_page_break_paragraph())

        # 深複製模板元素
        for elem in template_elements:
            elem_copy = copy.deepcopy(elem)
            new_body.append(elem_copy)

        # 取得剛加入的元素
        current_elements = [
            child for child in new_body
            if child.tag in (qn("w:p"), qn("w:tbl"))
        ]

        # 找出最後一個 section 的表格
        tables = [e for e in current_elements if e.tag == qn("w:tbl")]

        # info table (倒數第二個 table)
        info_table = tables[-2]
        # data table (最後一個 table)
        data_table = tables[-1]

        # 填入 info table
        _replace_table_cell(info_table, 0, 1, doctor.medical_institution)
        period = f"{data.report_year}年{data.report_month}月"
        _replace_table_cell(info_table, 1, 1, period)
        _replace_table_cell(info_table, 2, 1, doctor.doctor_name)

        # 填入 data table
        if doc_type == "prescription":
            counts = [doctor.exercise, doctor.nutrition,
                      doctor.emotion, doctor.social]
            fee = FEE_PER_PRESCRIPTION
        else:  # execution
            counts = [doctor.nutrition_exec, doctor.exercise_exec,
                      doctor.emotion_exec, doctor.social_exec]
            fee = FEE_PER_EXECUTION

        amounts = [c * fee for c in counts]
        total_count = sum(counts)
        total_amount = sum(amounts)

        for row_i in range(4):
            _replace_table_cell(data_table, row_i + 1, 2, str(counts[row_i]))
            _replace_table_cell(data_table, row_i + 1, 3, f"${amounts[row_i]:,}")

        # 總計列：w:tc 只有 3 個（第一個 gridSpan=2），所以 index 是 1 和 2
        _replace_table_cell(data_table, 5, 1, str(total_count))
        _replace_table_cell(data_table, 5, 2, f"${total_amount:,}")

        # 替換標題中的月份
        section_paras = [
            e for e in current_elements[-len(template_elements):]
            if e.tag == qn("w:p")
        ]

        # 找標題段落（第3個）替換月份
        title_idx = 0
        for elem in current_elements[-len(template_elements):]:
            if elem.tag == qn("w:p"):
                text = _get_element_text(elem)
                if "月" in text and ("處方費" in text or "執行費" in text):
                    # 替換月份文字
                    for run in elem.iter(qn("w:r")):
                        for t in run.iter(qn("w:t")):
                            if t.text and "年" in t.text:
                                t.text = f"{data.report_year}年{data.report_month:02d}月"

    new_doc.save(output_path)


def generate_prescription_fee_from_template(
    template_path: str, data: AllData, output_path: str
):
    generate_from_template(
        template_path, data, data.doctors, "prescription", output_path
    )


def generate_execution_fee_from_template(
    template_path: str, data: AllData, output_path: str
):
    generate_from_template(
        template_path, data, data.doctors, "execution", output_path
    )
