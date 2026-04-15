"""領據產生器 — 用實際 Word 檔當模板，直接替換數據

台灣扣繳規定：
- 單次給付 >= $20,000：扣繳 10% 所得稅 + 2.11% 二代健保補充保費 → 扣稅格式
- 單次給付 < $20,000：不扣稅格式
"""

import copy
import os
from docx import Document
from docx.oxml.ns import qn

from models import ReceiptInfo

TAX_THRESHOLD = 20000
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "word_templates")
TEMPLATE_NO_TAX = os.path.join(TEMPLATE_DIR, "領據_不扣稅_template.docx")
TEMPLATE_WITH_TAX = os.path.join(TEMPLATE_DIR, "領據_扣稅_template.docx")


def needs_tax(amount: int) -> bool:
    return amount >= TAX_THRESHOLD


def generate_receipt(receipt: ReceiptInfo, report_year: int,
                     report_month: int, output_path: str,
                     fee_title: str = "", fee_type: str = ""):
    """用模板產生領據，自動判斷扣稅/不扣稅"""
    if needs_tax(receipt.amount):
        template = TEMPLATE_WITH_TAX
    else:
        template = TEMPLATE_NO_TAX

    if not os.path.exists(template):
        raise FileNotFoundError(f"找不到領據模板: {template}")

    doc = Document(template)

    # 加費用類型文字後表格變高，清除「中華民國」前的段落間距避免溢頁
    if fee_type:
        for p_elem in doc.element.body.iter(qn("w:p")):
            pPr = p_elem.find(qn("w:pPr"))
            if pPr is not None:
                sp = pPr.find(qn("w:spacing"))
                if sp is not None:
                    for attr in list(sp.attrib.keys()):
                        if "before" in attr or "after" in attr:
                            sp.set(attr, "0")

    body = doc.element.body

    # 收集所有 text nodes
    all_texts = list(body.iter(qn("w:t")))

    # === 替換年月 ===
    _replace_year_month(all_texts, report_year, report_month)

    # === 替換金額 ===
    _replace_amount(doc, receipt.amount)

    # === 替換具領人名字 ===
    _replace_name(all_texts, receipt.recipient_name)

    # === 填入個人資料（身分證、地址、電話、銀行資訊）===
    _fill_personal_info(doc, receipt)

    # === 重組表格：茲收到(body→cell) / fee+確認 / 金額，全 jc=both line=600 ===
    if fee_type:
        _restructure_receipt_table(doc, fee_type)

    doc.save(output_path)


def _replace_year_month(all_texts, year: int, month: int):
    """替換年月數字

    原始結構：'茲收到' + '11' + '5' + '年' + '0' + '3' + '月' + ...
    或：'茲收到' + '115' + '年' + '3' + '月' + ...
    """
    year_str = str(year)
    month_str = f"{month:02d}"

    i = 0
    while i < len(all_texts):
        t = all_texts[i]
        if t.text and "茲收到" in t.text:
            # 找到起始點，接下來找年和月
            # 收集到「月」為止的所有 text nodes
            j = i + 1
            found_year = False
            found_month = False
            year_nodes = []
            month_nodes = []

            while j < len(all_texts) and not found_month:
                txt = all_texts[j].text or ""
                if "年" in txt:
                    found_year = True
                    # 年的數字在之前的 nodes
                    all_texts[j].text = "年"
                elif "月" in txt:
                    found_month = True
                    all_texts[j].text = "月"
                elif not found_year:
                    year_nodes.append(all_texts[j])
                elif found_year and not found_month:
                    month_nodes.append(all_texts[j])
                j += 1

            # 填入年份
            if year_nodes:
                year_nodes[0].text = year_str
                for node in year_nodes[1:]:
                    node.text = ""

            # 填入月份
            if month_nodes:
                month_nodes[0].text = month_str
                for node in month_nodes[1:]:
                    node.text = ""

            break
        i += 1


def _replace_amount(doc, amount: int):
    """替換金額（在表格 cell 中）"""
    amount_str = f"{amount:,}"

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                cell_text = cell.text
                if "元整" in cell_text or "新臺幣" in cell_text:
                    # 找到金額 cell，替換數字部分
                    texts = list(cell._tc.iter(qn("w:t")))
                    _replace_amount_in_texts(texts, amount_str)
                    return


def _replace_amount_in_texts(texts, amount_str: str):
    """在 text nodes 中替換金額數字

    原始結構可能是：'應付' + '新臺幣' + '6,0' + '00' + '元整' + ...
    或：'新臺幣' + '     122,400        ' + '元整'
    """
    # 找到「新臺幣」和「元整」之間的所有 nodes
    start_idx = None
    end_idx = None

    for i, t in enumerate(texts):
        txt = t.text or ""
        if "新臺幣" in txt:
            start_idx = i
        if "元整" in txt:
            end_idx = i
            break

    if start_idx is None or end_idx is None:
        return

    # 「新臺幣」和「元整」之間的 nodes 是金額
    if start_idx == end_idx:
        # 同一個 node 裡
        t = texts[start_idx]
        # Replace amount between 新臺幣 and 元整
        txt = t.text
        before = txt[:txt.index("新臺幣") + 3]
        after = txt[txt.index("元整"):]
        t.text = f"{before}{amount_str}{after}"
    else:
        amount_nodes = texts[start_idx + 1:end_idx]
        if amount_nodes:
            amount_nodes[0].text = amount_str
            for node in amount_nodes[1:]:
                node.text = ""
        else:
            # 新臺幣 node 和 元整 node 之間沒有 node
            # 把金額附加到新臺幣 node
            texts[start_idx].text = texts[start_idx].text + amount_str


def _append_confirm_after_amount_table(doc, fee_type: str):
    """把費用類型+確認文字用逗號接在「應付新臺幣」前，同一行，固定行距"""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if "元整" not in cell.text:
                    continue
                # 找含「應付」或「新臺幣」的第一個 text node
                for t in cell._tc.iter(qn("w:t")):
                    txt = t.text or ""
                    if "應付" in txt or "新臺幣" in txt:
                        # 把確認文字加在金額前面，用逗號相連
                        prefix = f"{fee_type}，確認金額明細如附件所示無誤請簽名，"
                        t.text = prefix + txt
                        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                        break

                # 設定含「元整」段落的固定行距（避免多行時行距不一致）
                for p in cell.paragraphs:
                    if "元整" in p.text or "應付" in p.text:
                        pPr = p._element.find(qn("w:pPr"))
                        if pPr is None:
                            pPr = parse_xml(f'<w:pPr {nsdecls("w")}/>')
                            p._element.insert(0, pPr)
                        # 移除舊 spacing，加固定行距
                        old_sp = pPr.find(qn("w:spacing"))
                        if old_sp is not None:
                            pPr.remove(old_sp)
                        pPr.append(parse_xml(
                            f'<w:spacing {nsdecls("w")} '
                            'w:line="480" w:lineRule="exact" '
                            'w:before="0" w:after="0"/>'
                        ))
                return


def _insert_fee_type(all_texts, fee_type: str):
    """在「照護計畫」文字後面接上費用類型 + 確認簽名文字，並縮小整段字體"""
    for t in all_texts:
        txt = t.text or ""
        if "照護計畫" in txt:
            t.text = txt + fee_type + "，確認金額明細如附件所示無誤請簽名"
            return


def _insert_confirm_after_amount(doc):
    """在金額表格後面插入「確認金額明細如附件所示無誤請簽名」"""
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from lxml import etree

    # 找到金額表格（含「元整」的表格）
    target_tbl = None
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if "元整" in cell.text:
                    target_tbl = table._tbl
                    break
            if target_tbl is not None:
                break
        if target_tbl is not None:
            break

    if target_tbl is None:
        return

    # 在表格後面建立新段落
    new_p = doc.add_paragraph()
    new_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    new_p.paragraph_format.space_before = Pt(6)
    new_p.paragraph_format.space_after = Pt(0)
    new_p.paragraph_format.line_spacing = 1.0
    run = new_p.add_run("確認金額明細如附件所示無誤請簽名")
    run.bold = True
    run.font.size = Pt(14)
    run.font.name = "標楷體"
    run.element.rPr.rFonts.set(qn("w:eastAsia"), "標楷體")

    # 把段落移到表格正後方
    target_tbl.addnext(new_p._element)


def _replace_name(all_texts, name: str):
    """替換具領人名字"""
    for i, t in enumerate(all_texts):
        txt = t.text or ""
        if "：" in txt or ":" in txt:
            continue
        # 找「具領人」後面跟著「：」再跟著名字的模式
        if txt == "：" or txt == ":":
            # 下一個非空 text 可能是名字
            # 但先確認前面是「具領人」相關
            pass

    # 更直接的方式：找到「具領人」標籤後的名字
    found_recipient = False
    for i, t in enumerate(all_texts):
        txt = t.text or ""
        if "具領" in txt:
            found_recipient = True
            continue
        if found_recipient and txt == "：":
            # 下一個有實際內容的 text 就是名字
            for j in range(i + 1, min(i + 5, len(all_texts))):
                next_txt = all_texts[j].text or ""
                next_txt = next_txt.strip()
                if next_txt and next_txt not in ("", " ", "　"):
                    all_texts[j].text = name
                    return
            # 如果沒找到，在冒號後面加
            if i + 1 < len(all_texts):
                if all_texts[i + 1].text and all_texts[i + 1].text.strip():
                    all_texts[i + 1].text = " " + name
                elif i + 2 < len(all_texts):
                    all_texts[i + 2].text = name
            return


def _fill_personal_info(doc, receipt):
    """填入個人資料（身分證、地址、電話、銀行資訊）

    兩種模板結構都支援：
    - 不扣稅：欄位在 body 段落（「身分證字號：」獨立段落）
    - 扣稅：欄位在表格 cell 內段落
    以段落為單位：找到含關鍵字的段落，在「：」後填入值。
    """
    FILL_MAP = [
        ("身分證",    receipt.id_number),
        ("戶籍",      receipt.address),
        ("聯絡電話",  receipt.phone),
        ("戶名",      receipt.account_name),
        ("銀行及分行", receipt.bank_branch),
        ("銀行代碼",  receipt.bank_code),
        ("帳號",      receipt.account_number),
    ]

    # 收集所有段落：body + 表格 cell 內
    all_paras = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                all_paras.extend(cell.paragraphs)

    for keyword, value in FILL_MAP:
        if not value:
            continue
        for para in all_paras:
            if keyword in para.text:
                _fill_para_after_colon(para, value)
                break  # 每個 keyword 只填第一個匹配的段落


def _fill_para_after_colon(para, value: str):
    """在段落的 w:t 串中找到「：」，將值填入冒號後面

    規則：
    - 若冒號後同一段落有下一個 w:t → 覆蓋那個節點
    - 若冒號是段落最後一個 w:t → 直接在冒號節點後附加值
    值填入後，若原 run 字體 > 14pt 且值較長，縮小至 14pt 防止換行。
    """
    wts = list(para._element.iter(qn("w:t")))
    for i, wt in enumerate(wts):
        txt = wt.text or ""
        for sep in ("：", ":"):
            if sep not in txt:
                continue
            colon_pos = txt.index(sep)
            existing_after = txt[colon_pos + 1:].strip()
            if existing_after:
                # 冒號後已有值，直接覆蓋
                target_wt = wt
                wt.text = txt[: colon_pos + 1] + value
                wt.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            elif i + 1 < len(wts):
                # 冒號後有下一個 w:t，填入那裡
                target_wt = wts[i + 1]
                wts[i + 1].text = value
                wts[i + 1].set(
                    "{http://www.w3.org/XML/1998/namespace}space", "preserve"
                )
            else:
                # 冒號是最後一個 w:t，直接附加
                target_wt = wt
                wt.text = txt[: colon_pos + 1] + value
                wt.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

            # 只有「空格縮排」段落（無 firstLine indent）才縮小字體；
            # firstLine indent 段落縮小字體會影響縮排比例（不縮）
            has_first_line = _para_has_firstline_indent(para)
            if not has_first_line and len(value) > 11:
                # 自適應字體大小：讓長文字盡量在一行內顯示
                # 14pt（28 half-pt）約可放 18 個中文字；依比例縮，最小 10pt（20）
                CHARS_AT_14PT = 18
                if len(value) > CHARS_AT_14PT:
                    max_sz = max(20, int(28 * CHARS_AT_14PT / len(value)))
                else:
                    max_sz = 28  # 14pt
                for wt in wts:
                    if (wt.text or "").strip():
                        _shrink_run_font(wt, max_sz=max_sz)
            return


def _shrink_run_font(wt_elem, max_sz: int = 28):
    """將 w:t 的父 run 字體設為 max_sz（half-pt）
    若 run 或 rPr 不存在則建立；若無明確 w:sz 則直接新增（預設繼承樣式通常 > 14pt）。
    """
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    run = wt_elem.getparent()
    if run is None:
        return
    rPr = run.find(qn("w:rPr"))
    if rPr is None:
        rPr = parse_xml(f'<w:rPr {nsdecls("w")}/>')
        run.insert(0, rPr)
    for tag in (qn("w:sz"), qn("w:szCs")):
        sz_el = rPr.find(tag)
        if sz_el is None:
            # 無明確字體設定，直接新增 max_sz
            from lxml import etree
            sz_el = etree.SubElement(rPr, tag)
            sz_el.set(qn("w:val"), str(max_sz))
        else:
            try:
                val = int(sz_el.get(qn("w:val"), "0"))
                if val > max_sz or val == 0:
                    sz_el.set(qn("w:val"), str(max_sz))
            except ValueError:
                sz_el.set(qn("w:val"), str(max_sz))


def _para_has_firstline_indent(para) -> bool:
    """段落是否用 firstLine indent（而非 leading spaces）做縮排"""
    pPr = para._element.find(qn("w:pPr"))
    if pPr is None:
        return False
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        return False
    return ind.get(qn("w:firstLine")) is not None


def _hide_table_borders(table):
    """把表格所有框線設為 none（隱藏）"""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    tbl = table._tbl
    tblPr = tbl.find(qn("w:tblPr"))
    if tblPr is None:
        tblPr = parse_xml(f'<w:tblPr {nsdecls("w")}/>')
        tbl.insert(0, tblPr)
    # 移除舊 borders
    old = tblPr.find(qn("w:tblBorders"))
    if old is not None:
        tblPr.remove(old)
    # 加全 none 框線
    tblPr.append(parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        '<w:top w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        '<w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        '<w:bottom w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        '<w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        '<w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        '<w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        '</w:tblBorders>'
    ))


def _scale_paragraph_fonts(doc, keyword: str, scale: float):
    """找到含 keyword 的段落，把該段落所有 run 字體等比縮放"""
    body = doc.element.body
    for para in body.findall(qn("w:p")):
        # 收集此段落所有文字
        texts = "".join(
            t.text or "" for t in para.iter(qn("w:t"))
        )
        if keyword not in texts:
            continue
        for r in para.findall(qn("w:r")):
            rPr = r.find(qn("w:rPr"))
            if rPr is None:
                continue
            for tag in (qn("w:sz"), qn("w:szCs")):
                sz_el = rPr.find(tag)
                if sz_el is not None:
                    try:
                        val = int(sz_el.get(qn("w:val"), "0"))
                        if val > 0:
                            sz_el.set(qn("w:val"), str(max(16, int(val * scale))))
                    except ValueError:
                        pass
        break  # 只處理找到的第一個


def _restructure_receipt_table(doc, fee_type: str):
    """將茲收到/費用類型/金額改為純文字段落，刪除原表格（避免邊框）

    輸出：body 中插入三個純段落（無表格），格式 jc=both line=600 exact sz=40
        [茲收到...-]
        [{fee_type}處方處置費。]
        [應付新臺幣 X 元整(阿拉伯數字)。]
    """
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    PARA_XML_TMPL = (
        f'<w:p {nsdecls("w")}>'
        f'<w:pPr>'
        f'<w:spacing w:line="600" w:lineRule="exact" w:before="0" w:after="0"/>'
        f'<w:jc w:val="both"/>'
        f'</w:pPr>'
        f'<w:r>'
        f'<w:rPr>'
        f'<w:rFonts w:ascii="標楷體" w:eastAsia="標楷體"/>'
        f'<w:sz w:val="40"/><w:szCs w:val="40"/>'
        f'</w:rPr>'
        f'<w:t xml:space="preserve">{{text}}</w:t>'
        f'</w:r>'
        f'</w:p>'
    )

    def make_para(text: str):
        return parse_xml(PARA_XML_TMPL.format(text=text))

    # 1. 找「茲收到」body 段落
    zi_text = ""
    zi_para = None
    for p in doc.paragraphs:
        if "茲收到" in p.text:
            zi_text = p.text.strip()
            zi_para = p
            break
    if zi_para is None:
        return

    # 2. 找含「元整」的表格，提取金額文字
    amount_text = ""
    target_tbl = None
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if "元整" not in cell.text:
                    continue
                for p in cell.paragraphs:
                    if "元整" in p.text or "應付" in p.text:
                        amount_text = p.text.strip()
                        break
                if amount_text:
                    target_tbl = table._tbl
                    break
            if target_tbl is not None:
                break
        if target_tbl is not None:
            break

    if not amount_text or target_tbl is None:
        return

    # 3. 在表格位置插入三個純文字段落（zi → fee → amount）
    tbl_parent = target_tbl.getparent()
    amount_p = make_para(amount_text)
    fee_p    = make_para(f"{fee_type}。")
    zi_p     = make_para(zi_text + "-")

    # addprevious 每次都插在 table 正前方，所以按 zi→fee→amount 順序插
    target_tbl.addprevious(zi_p)
    target_tbl.addprevious(fee_p)
    target_tbl.addprevious(amount_p)

    # 4. 刪除表格
    tbl_parent.remove(target_tbl)

    # 5. 刪除原本 body 的「茲收到」段落
    zi_para._element.getparent().remove(zi_para._element)
