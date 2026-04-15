"""從實際的 Word 文件中提取一位醫師的區塊，建立模板。

這個腳本會：
1. 讀取用戶提供的實際 Word 檔（如 3 月處方費總表）
2. 提取第一位醫師的完整區塊（標題 + 資訊表 + 資料表 + 註 + 簽章）
3. 將數值替換為 Jinja2 模板變數
4. 儲存為模板檔案
"""

import copy
import sys
import os

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn


def extract_single_doctor_section(src_doc, start_table_idx=0):
    """提取一位醫師的完整 section（從 info table 到 signature line）

    Returns list of XML elements (paragraphs and tables)
    """
    body = src_doc.element.body
    elements = list(body)

    # Find the elements between table pairs
    table_count = 0
    section_elements = []
    in_section = False
    found_tables = 0

    for elem in elements:
        is_table = elem.tag == qn("w:tbl")
        is_para = elem.tag == qn("w:p")

        if is_table:
            table_count += 1

        if table_count == start_table_idx + 1:
            in_section = True

        if in_section:
            section_elements.append(elem)
            if is_table:
                found_tables += 1
            # After 2 tables and 2+ paragraphs past signature, stop
            if found_tables >= 2 and is_para:
                text = elem.text or ""
                # Check if we've passed the signature line
                para_texts = [
                    node.text for node in elem.iter(qn("w:t")) if node.text
                ]
                full_text = "".join(para_texts)
                if "確認簽章" in full_text:
                    # Include one more paragraph (empty line after signature)
                    continue
                if found_tables >= 2 and len(section_elements) > 10:
                    # We've collected enough - check if next element starts
                    # a new section
                    break

    return section_elements


def create_prescription_fee_template(src_path, output_path):
    """從實際處方費文件建立模板"""
    src_doc = Document(src_path)

    # Create new doc preserving styles from source
    template_doc = Document(src_path)

    # Clear all content
    body = template_doc.element.body
    for child in list(body):
        if child.tag in (qn("w:p"), qn("w:tbl")):
            body.remove(child)

    # Now we need to rebuild one section with template variables
    # Get the first section from source as reference
    src_body = src_doc.element.body

    # Find all paragraphs and tables in order
    elements = []
    for child in src_body:
        if child.tag in (qn("w:p"), qn("w:tbl")):
            elements.append(child)

    # The pattern for one doctor section:
    # P: title 1 (台北市醫師公會...)
    # P: title 2 (臺北市慢性病...)
    # P: title 3 (XX月處方費核銷總表)
    # P: empty
    # T: info table (3x2)
    # P: empty
    # T: data table (6x4)
    # P: empty
    # P: 註:
    # P: 1. ...
    # P: 2. ...
    # P: empty
    # P: 確認簽章

    # Count elements up to second table end + notes + signature
    first_section_end = 0
    table_count = 0
    for i, elem in enumerate(elements):
        if elem.tag == qn("w:tbl"):
            table_count += 1
        if table_count >= 2:
            # Look for signature line
            if elem.tag == qn("w:p"):
                texts = [n.text for n in elem.iter(qn("w:t")) if n.text]
                if "確認簽章" in "".join(texts):
                    first_section_end = i
                    break

    if first_section_end == 0:
        print("Warning: Could not find section boundary")
        first_section_end = 13  # fallback

    # Copy elements for one section
    for i in range(first_section_end + 1):
        elem_copy = copy.deepcopy(elements[i])
        body.append(elem_copy)

    template_doc.save(output_path)
    print(f"Template saved: {output_path}")
    print(f"  Copied {first_section_end + 1} elements from source")


if __name__ == "__main__":
    src = r"C:\Users\s7104\OneDrive\文件\健康台灣深耕計畫_處方費-總表-115年03月.docx"
    out_dir = os.path.join(os.path.dirname(__file__), "word_templates")
    os.makedirs(out_dir, exist_ok=True)

    create_prescription_fee_template(
        src, os.path.join(out_dir, "處方費核銷總表_template.docx")
    )
