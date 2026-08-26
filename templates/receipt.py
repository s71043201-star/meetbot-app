"""領據產生器 — 用實際 Word 檔當模板，純填空（保留原 rPr/pPr）

模板（2026-04 重構，pivot 表結構）:
- 領據_不扣稅_template.docx：處方費+執行費合併版，amount < 20000
  Body: 標題 + Table 0 (5×6 pivot：費用項目/4 處方/總計 × 處方處方費/處方執行費/金額)
        + 備註 + HR + 茲收到/此致/個資 + 中華民國
- 領據_扣稅_template.docx：處方費+執行費合併版，amount >= 20000
  Body: 標題 + Table 0 + 備註 + 大表格(含 nested 應付/代扣2.11%/代扣所得稅/實付 + 個資)
        + 中華民國
- 領據_處置費_template.docx：處置費，amount < 20000
  Body: 標題 + Table 0 (4×6 pivot：處方處置費/金額) + 備註 + HR + 茲收到/此致/個資 + 中華民國
- 領據_處置費_扣稅_template.docx：處置費，amount >= 20000
  Body: 同扣稅但 Table 0 為處置費 4×6 pivot
- 領據_健管費_template.docx：健管費 (5 欄表 含達標欄，不變)

台灣扣繳（依報稅類別）：
  二代健保 2.11%：執業所得 >= 20,000 / 薪資 >= 29,500 即扣。
  所得稅：執業所得 10%（> 20,000）/ 薪資 5%（> 90,500 起扣標準，不含）。
"""

import copy
import os
import re
from typing import Dict, Optional

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

from models import ReceiptInfo
from treatment_fees import (
    DEFAULT_LABEL as TREATMENT_DEFAULT_LABEL,
    fee_for_label as treatment_fee_for_label,
    ordered_labels as treatment_labels,
)
from tax_rules import (
    withhold, category_for, nhi_threshold,
    income_tax_rate, income_tax_threshold, SALARY,
)

# 為相容既有匯入而保留；實際扣繳改由 tax_rules.withhold 依報稅類別計算
from config import INCOME_TAX_THRESHOLD as TAX_THRESHOLD, NHI_RATE, INCOME_TAX_RATE

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "word_templates")
# 統一使用扣稅版型；金額 < 20000 時於應付/代扣/實付區寫「不需扣稅」。
TEMPLATE_WITH_TAX = os.path.join(TEMPLATE_DIR, "領據_扣稅_template.docx")
TEMPLATE_TREATMENT_TAX = os.path.join(TEMPLATE_DIR, "領據_處置費_扣稅_template.docx")
TEMPLATE_HEALTH_MGMT = os.path.join(TEMPLATE_DIR, "領據_健管費_template.docx")

# pivot 表的處方類型欄順序(必須符合模板 R1 的欄位順序)
# 跟民眾明細表一致:運動 → 營養 → 情緒調適 → 社會
PIVOT_COL_ORDER = ["運動處方", "營養處方", "情緒調適處方", "社會處方"]


def needs_tax(amount: int) -> bool:
    return amount >= TAX_THRESHOLD


def _is_treatment(fee_type: str) -> bool:
    return bool(fee_type) and "處方處置費" in fee_type


def _is_health_mgmt(fee_type: str) -> bool:
    return bool(fee_type) and "健康管理" in fee_type


def generate_receipt(receipt: ReceiptInfo, report_year: int,
                     report_month: int, output_path: str,
                     fee_type: str = "",
                     # 合併版（處方費 + 執行費）所需 dict
                     presc_counts: Optional[Dict[str, int]] = None,
                     exec_counts: Optional[Dict[str, int]] = None,
                     fee_per_presc: int = 300,
                     fee_per_exec: int = 100,
                     # 處置費
                     treatment_counts: Optional[Dict[str, int]] = None,
                     treatment_course_counts: Optional[Dict[str, Dict[str, int]]] = None,
                     fee_per_treatment: int = 400,
                     # 健管費
                     people_count: int = 0,
                     prescription_count: int = 0,
                     is_qualified: bool = True):
    """產生領據（純填空，保留模板原 rPr/pPr）

    Args:
        fee_type: 茲收到段落要塞的整段描述，會替換預設的「運動、營養、社會、情緒調適處方處方費」
        presc_counts/exec_counts: 處方費+執行費合併版的份數 dict（key = 處方類型名）
        treatment_counts: 處置費 pivot 的份數 dict（{處方類型: 人次}）— 舊呼叫端用，
                          單一 400 元費率；未給 treatment_course_counts 時才生效
        treatment_course_counts: 處置費費率分流後的份數（{費率標籤: {處方類型: 人次}}）。
                          一般課程 400 / 處方PLUS2 200 / 視訊課程 100，pivot 表依此分列
        fee_per_presc/exec/treatment: 單份單價
        people_count/prescription_count/is_qualified: 健管費 Table 0 用
    """
    # 統一使用扣稅版型（含應付/代扣/實付區）；金額 < 20000 時 _fill_tax_amounts
    # 會寫「不需扣稅」、實付 = 應付
    if _is_health_mgmt(fee_type):
        template = TEMPLATE_HEALTH_MGMT
    elif _is_treatment(fee_type):
        template = TEMPLATE_TREATMENT_TAX
    else:
        template = TEMPLATE_WITH_TAX

    if not os.path.exists(template):
        raise FileNotFoundError(f"找不到領據模板: {template}")

    doc = Document(template)
    body = doc.element.body
    all_texts = list(body.iter(qn("w:t")))

    _replace_year_month(all_texts, report_year, report_month)

    if fee_type:
        _replace_fee_sentence(all_texts, fee_type)

    # 填 Table 0
    if _is_health_mgmt(fee_type):
        _fill_summary_table_health_mgmt(
            doc, people_count, prescription_count,
            is_qualified, receipt.amount)
    elif _is_treatment(fee_type):
        # 費率分流：有 treatment_course_counts 就依課程型態分列；
        # 舊呼叫端(或來源檔沒有「執行課程」欄)則全歸一般課程費率，版面同舊版。
        course_counts = treatment_course_counts
        if not course_counts:
            course_counts = {
                TREATMENT_DEFAULT_LABEL: dict(treatment_counts or {})
            }
        extra_rows = _fill_pivot_treatment(doc, course_counts)
        _replace_treatment_note(all_texts, course_counts)
        # 多長的列會把末行「中華民國…」頂到第二頁 → 回收等量留白維持一頁。
        # 多回收 1 個當緩衝：金額位數多時「茲收到…元整」會多折一行(24pt)，
        # 那本來是模板僅剩的餘裕，被多出的列吃掉就會超頁。
        if extra_rows > 0:
            _reclaim_blank_paragraphs(doc, extra_rows + 1)
    else:
        _fill_pivot_combined(doc, presc_counts or {}, exec_counts or {},
                              fee_per_presc, fee_per_exec)

    # 重新蒐集（cell 填值可能改了結構）
    all_texts = list(body.iter(qn("w:t")))
    _replace_amount_in_paragraphs(all_texts, receipt.amount)

    if not _is_health_mgmt(fee_type):
        role_hint = "課程老師" if _is_treatment(fee_type) else "醫師"
        category = category_for(receipt.occupation, role_hint)
        _fill_tax_box_text(doc, category)
        _fill_tax_amounts(doc, receipt.amount, category)

    _replace_name(all_texts, receipt.recipient_name)

    _fix_personal_info_indent(doc)

    _fill_personal_info_xml(doc, receipt)

    doc.save(output_path)


# ============================================================
#  年月、費用句、姓名等 inline 替換
# ============================================================

def _replace_year_month(all_texts, year: int, month: int):
    """將「茲收到 XXX 年 YYY 月」替換為民國年 / 兩位數月份"""
    year_str = str(year)
    month_str = f"{month:02d}"
    pattern = re.compile(r'茲收到\s*\d+\s*年\s*\d*\s*月')

    for t in all_texts:
        txt = t.text or ""
        if pattern.search(txt):
            t.text = pattern.sub(
                f"茲收到 {year_str} 年 {month_str} 月", txt, count=1)
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            return


def _replace_fee_sentence(all_texts, fee_type: str):
    """將模板裡的「運動、營養、情緒調適、社會處方處方費」替換為 fee_type。

    Word 常把同一段中文切到多個 <w:t> run(因為部份字套了不同字型/底線),
    所以這裡先把整份 run 串連起來找位置,再跨 run 重寫。
    """
    DEFAULT = "運動、營養、情緒調適、社會處方處方費"
    if fee_type == DEFAULT:
        return

    # 1) DEFAULT 完整在同一個 run
    for t in all_texts:
        txt = t.text or ""
        if DEFAULT in txt:
            t.text = txt.replace(DEFAULT, fee_type)
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            return

    # 2) DEFAULT 跨多個 run:把所有 run 串接起來找位置,再依序覆寫
    concat = ""
    spans: list[tuple[int, int, int]] = []  # (start, run_idx, length)
    for idx, t in enumerate(all_texts):
        txt = t.text or ""
        spans.append((len(concat), idx, len(txt)))
        concat += txt

    pos = concat.find(DEFAULT)
    if pos < 0:
        return
    end = pos + len(DEFAULT)

    first = next(
        ((s, i, l) for s, i, l in spans if s <= pos < s + l),
        None,
    )
    last = next(
        ((s, i, l) for s, i, l in spans if s < end <= s + l),
        None,
    )
    if first is None or last is None:
        return

    f_start, f_idx, _ = first
    l_start, l_idx, _ = last
    prefix = (all_texts[f_idx].text or "")[: pos - f_start]
    suffix = (all_texts[l_idx].text or "")[end - l_start:]

    preserve = "{http://www.w3.org/XML/1998/namespace}space"
    if f_idx == l_idx:
        all_texts[f_idx].text = prefix + fee_type + suffix
        all_texts[f_idx].set(preserve, "preserve")
    else:
        all_texts[f_idx].text = prefix + fee_type
        all_texts[f_idx].set(preserve, "preserve")
        for i in range(f_idx + 1, l_idx):
            all_texts[i].text = ""
        all_texts[l_idx].text = suffix
        all_texts[l_idx].set(preserve, "preserve")


def _replace_amount_in_paragraphs(all_texts, amount: int):
    """將「(應付)新臺幣 ___ 元整」段落中間的空白/數字替換為實際金額。

    金額塞進「中間」(i+1) 那個 placeholder 節點以保留其 run 格式（如底線）。
    新臺幣節點 / 元整節點 不動，只清空 i+2..j-1 中間其他空白節點。
    模板「元整」run 帶 w:u="single" 底線；當 i 與 j 相鄰時，需另行插入
    一個帶底線的 run 給金額，讓「金額 + 元整」連成一條底線。
    """
    amount_str = f"{amount:,}"

    for i, t in enumerate(all_texts):
        txt = t.text or ""
        if "新臺幣" not in txt:
            continue
        j = i
        while j < len(all_texts):
            jtxt = all_texts[j].text or ""
            if "元整" in jtxt:
                break
            j += 1
        if j >= len(all_texts):
            continue

        if i == j:
            # 同一節點：直接 inline 替換
            t.text = re.sub(
                r'(新臺幣)([^元]*)(元整)',
                f"\\1 {amount_str} \\3",
                txt, count=1
            )
            t.set(
                "{http://www.w3.org/XML/1998/namespace}space", "preserve")
        else:
            middle = list(range(i + 1, j))
            if middle:
                # 用「中間 placeholder」node 放金額，保留底線等格式
                all_texts[middle[0]].text = f" {amount_str} "
                all_texts[middle[0]].set(
                    "{http://www.w3.org/XML/1998/namespace}space", "preserve")
                for k in middle[1:]:
                    all_texts[k].text = ""
            else:
                # i 與 j 相鄰：把「新臺幣」後面的空白佔位符替換成金額。
                # 模板「元整」run 帶底線，要讓金額也帶同樣底線才能連成一條，
                # 因此在 i 與 j 之間「插入新 run」承載金額（rPr 沿用 j run）。
                #
                # 1. 先把 i 節點末尾多餘空白清掉，「新臺幣」後留 1 格
                all_texts[i].text = re.sub(r'(新臺幣)\s*$', r"\1 ", txt)
                all_texts[i].set(
                    "{http://www.w3.org/XML/1998/namespace}space", "preserve")
                # 2. 在 j 對應的 run 之前插入一個新 run（包含金額 + 帶底線 rPr）
                import copy
                from lxml import etree
                j_run = all_texts[j].getparent()  # w:r
                if j_run is not None:
                    j_rPr = j_run.find(qn("w:rPr"))
                    new_r = etree.Element(qn("w:r"))
                    if j_rPr is not None:
                        new_r.append(copy.deepcopy(j_rPr))
                    new_t = etree.SubElement(new_r, qn("w:t"))
                    new_t.set(
                        "{http://www.w3.org/XML/1998/namespace}space", "preserve")
                    new_t.text = f"{amount_str} "
                    j_run.addprevious(new_r)
        return


def _replace_name(all_texts, name: str):
    """填具領人姓名（在「具領人：」後）"""
    if not name:
        return
    for t in all_texts:
        txt = t.text or ""
        if "具領人：" in txt and "用印" not in txt:
            t.text = txt.replace("具領人：", f"具領人：{name}", 1)
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            return


# ============================================================
#  Table 0 填值
# ============================================================

def _find_pivot_table(doc):
    """找含「處方類型」表頭、且非健管費（無「達標」）的 pivot 表"""
    body = doc.element.body
    for tbl in body.iter(qn("w:tbl")):
        first_row = tbl.find(qn("w:tr"))
        if first_row is None:
            continue
        ftxt = "".join(t.text or "" for t in first_row.iter(qn("w:t")))
        if "處方類型" in ftxt and "達標" not in ftxt:
            return tbl
    return None


def _fill_pivot_combined(doc, presc_counts: Dict[str, int],
                          exec_counts: Dict[str, int],
                          fee_per_presc: int, fee_per_exec: int):
    """填合併版 pivot 表 (5×6)
    R0: 空 | 處方類型(gs=5)            ← 表頭，不動
    R1: 費用項目(元) | 4處方 | 總計     ← 表頭，不動
    R2: 處方處方費 | 份數×4 | 處方費總額
    R3: 處方執行費 | 份數×4 | 執行費總額
    R4: 金額(元)  | 各類型總金額×4 | 全部總計
    """
    target = _find_pivot_table(doc)
    if target is None:
        return
    all_rows = target.findall(qn("w:tr"))
    if len(all_rows) < 5:
        return

    def fill_row(row_cells, values):
        """row_cells 預期 6 個 cell（含 label cell）；values 為 5 個字串對應後 5 cell"""
        if len(row_cells) < 6:
            return
        for i, v in enumerate(values):
            if v is not None:
                _set_cell_text(row_cells[1 + i], v)

    # R2: 處方處方費
    r2_cells = all_rows[2].findall(qn("w:tc"))
    presc_total_count = sum(presc_counts.get(pt, 0) for pt in PIVOT_COL_ORDER)
    presc_total_amount = presc_total_count * fee_per_presc
    fill_row(r2_cells, [
        str(presc_counts.get(pt, 0)) if presc_counts.get(pt, 0) > 0 else "-"
        for pt in PIVOT_COL_ORDER
    ] + [f"{presc_total_amount:,}" if presc_total_amount > 0 else "-"])

    # R3: 處方執行費
    r3_cells = all_rows[3].findall(qn("w:tc"))
    exec_total_count = sum(exec_counts.get(pt, 0) for pt in PIVOT_COL_ORDER)
    exec_total_amount = exec_total_count * fee_per_exec
    fill_row(r3_cells, [
        str(exec_counts.get(pt, 0)) if exec_counts.get(pt, 0) > 0 else "-"
        for pt in PIVOT_COL_ORDER
    ] + [f"{exec_total_amount:,}" if exec_total_amount > 0 else "-"])

    # R4: 金額(元) — 各 type 的 (處方費 + 執行費) 總額
    r4_cells = all_rows[4].findall(qn("w:tc"))
    grand_total = 0
    per_col_amounts = []
    for pt in PIVOT_COL_ORDER:
        amt = (presc_counts.get(pt, 0) * fee_per_presc
               + exec_counts.get(pt, 0) * fee_per_exec)
        per_col_amounts.append(f"{amt:,}" if amt > 0 else "-")
        grand_total += amt
    fill_row(r4_cells, per_col_amounts +
             [f"{grand_total:,}" if grand_total > 0 else "-"])


# 處置費列標籤的短稱 — 第一欄只有 3.83cm，實測 14pt 下超過 6 個中文字寬就
# 折行變兩列、把領據頂到第二頁。各費率的單價寫在備註，這裡不重複。
# 多費率時 R1 的欄名 — 把「處置費」放在這裡，各列就不必重複前綴。
# 第一欄只有 3.83cm，實測「處置費-一般實體課程」「處置費項目(元)」都會折行，
# 而「處置費項目」+ 各列全名剛好都排得進一行，且完全不用動頁面邊距
# (改邊距會把下半部的扣稅表格與個資區擠爆)。
TREATMENT_PIVOT_HEADER = "處置費項目"


def _treatment_row_label(label: str) -> str:
    """費率標籤 → pivot 表第一欄文字(費率全名，不加前綴)"""
    return str(label)


def _active_treatment_labels(course_counts) -> list:
    """回傳「實際有人次」的費率標籤，照固定顯示順序。

    只列有資料的費率是維持領據一頁的關鍵：單一費率時表格列數與舊版相同，
    版面完全不變；兩種以上才長列。
    """
    counts = course_counts or {}
    labels = [lb for lb in treatment_labels()
              if sum((counts.get(lb) or {}).values()) > 0]
    # config 改過而 ordered_labels 未收錄的自訂標籤也要列出，不能漏算金額
    for lb in counts:
        if lb not in labels and sum((counts.get(lb) or {}).values()) > 0:
            labels.append(lb)
    return labels


def _fill_pivot_treatment(doc, course_counts: Dict[str, Dict[str, int]]):
    """填處置費 pivot 表 — 依費率(課程型態)分列

    course_counts: {費率標籤: {處方類型: 人次}}
      例 {"一般課程": {"運動處方": 8}, "處方PLUS2": {"情緒調適處方": 12}}

    模板本身只有 1 個資料列(R2)，實際有幾種費率就把它複製成幾列：
      R0: 空 | 處方類型(gs=5)
      R1: 費用項目(元) | 4 處方 | 總計
      R2..Rn: 處置費/{型態} | 人次×4 | 該費率總額
      末列: 金額(元) | 各處方類型金額×4 | 全部總計

    單一費率時只有 1 個資料列，與舊版 4×6 完全相同(領據維持一頁)。
    """
    target = _find_pivot_table(doc)
    if target is None:
        return 0
    all_rows = target.findall(qn("w:tr"))
    if len(all_rows) < 4:
        return 0

    def fill_row(row_cells, values):
        if len(row_cells) < 6:
            return
        for i, v in enumerate(values):
            if v is not None:
                _set_cell_text(row_cells[1 + i], v)

    labels = _active_treatment_labels(course_counts)
    if not labels:
        labels = [TREATMENT_DEFAULT_LABEL]

    # 單一且為預設費率 → 完全沿用模板(欄名「費用項目(元)」+「處方處置費」);
    # 否則各列改印費率全名，欄名同步換成「處置費項目」把「處置費」帶進表裡。
    if not (len(labels) == 1 and labels[0] == TREATMENT_DEFAULT_LABEL):
        hdr_cells = all_rows[1].findall(qn("w:tc"))
        if hdr_cells:
            _set_cell_text(hdr_cells[0], TREATMENT_PIVOT_HEADER)

    template_row = all_rows[2]   # 資料列範本
    amount_row = all_rows[-1]    # 金額(元) 列，永遠留在最後

    # 需要 len(labels) 個資料列：第 1 個用模板原列，其餘複製插在金額列之前
    data_rows = [template_row]
    for _ in range(len(labels) - 1):
        new_row = copy.deepcopy(template_row)
        amount_row.addprevious(new_row)
        data_rows.append(new_row)

    # 單一且為預設費率 → 第一欄沿用模板原文字「處方處置費」，版面零變動
    single = (len(labels) == 1 and labels[0] == TREATMENT_DEFAULT_LABEL)

    for row, label in zip(data_rows, labels):
        cells = row.findall(qn("w:tc"))
        if len(cells) < 6:
            continue
        per_type = course_counts.get(label) or {}
        unit = treatment_fee_for_label(label)
        if not single:
            _set_cell_text(cells[0], _treatment_row_label(label))
        row_total = sum(per_type.get(pt, 0) for pt in PIVOT_COL_ORDER) * unit
        fill_row(cells, [
            str(per_type.get(pt, 0)) if per_type.get(pt, 0) > 0 else "-"
            for pt in PIVOT_COL_ORDER
        ] + [f"{row_total:,}" if row_total > 0 else "-"])

    # 末列 金額(元)：同一處方類型跨費率相加
    amount_cells = amount_row.findall(qn("w:tc"))
    grand = 0
    per_col = []
    for pt in PIVOT_COL_ORDER:
        amt = sum((course_counts.get(lb) or {}).get(pt, 0)
                  * treatment_fee_for_label(lb) for lb in labels)
        per_col.append(f"{amt:,}" if amt > 0 else "-")
        grand += amt
    fill_row(amount_cells, per_col +
             [f"{grand:,}" if grand > 0 else "-"])

    # 比模板原本(1 個資料列)多出的列數 → 呼叫端據此回收等量留白
    return len(labels) - 1


def _reclaim_blank_paragraphs(doc, extra_rows: int) -> int:
    """處置費領據多長幾列時，回收等量高度的空段落，讓領據維持一頁。

    領據必須印在同一頁。pivot 表每多一個費率就多一列(14pt 字 + 儲存格
    padding ≈ 16.5pt)，實測 3 種費率(多 2 列)就會把末行「中華民國 年 月 日」
    頂到第二頁。文件裡本來有數個純留白空段落(每個約 15~19pt)，每多一列就
    回收一個，高度剛好換回來。

    回收順序刻意分散，避免某一處突然變擠：
      1. pivot 表與「備註：」之間的空段落
      2. 文末簽署留白(至少保留 1 個)

    回傳實際回收的段落數(可能少於 extra_rows，模板留白不足時)。
    """
    if extra_rows <= 0:
        return 0

    body = doc.element.body
    children = list(body)

    def is_blank_p(el):
        if el.tag != qn("w:p"):
            return False
        return not "".join(t.text or "" for t in el.iter(qn("w:t"))).strip()

    first_tbl = next((i for i, el in enumerate(children)
                      if el.tag == qn("w:tbl")), None)
    last_tbl = next((i for i in range(len(children) - 1, -1, -1)
                     if children[i].tag == qn("w:tbl")), None)
    note_idx = next(
        (i for i, el in enumerate(children)
         if el.tag == qn("w:p")
         and "備註" in "".join(t.text or "" for t in el.iter(qn("w:t")))),
        None)

    # 1) pivot 表之後、「備註：」之前
    group_a = []
    if first_tbl is not None and note_idx is not None and note_idx > first_tbl:
        group_a = [el for el in children[first_tbl + 1:note_idx]
                   if is_blank_p(el)]

    # 2) 最後一個表格之後的文末留白(倒序回收，保留 1 個)
    group_b = []
    if last_tbl is not None:
        tail_blanks = [el for el in children[last_tbl + 1:] if is_blank_p(el)]
        group_b = list(reversed(tail_blanks))[1:]

    # 3) 中段其他留白(備註與支領內容摘要之間、實付表格與個資之間)。
    #    金額位數多時「茲收到…新臺幣 X 元整」會多折一行(24pt)，光靠 1、2 兩
    #    處不一定夠，這裡當備援。
    group_c = []
    if note_idx is not None:
        used = set(id(el) for el in group_a + group_b)
        group_c = [el for el in children[note_idx + 1:]
                   if is_blank_p(el) and id(el) not in used]
        # 文末那個保留的留白不能動
        if last_tbl is not None:
            tail_blanks = [el for el in children[last_tbl + 1:] if is_blank_p(el)]
            if tail_blanks:
                keep = id(tail_blanks[-1])
                group_c = [el for el in group_c if id(el) != keep]

    removed = 0
    for el in group_a + group_b + group_c:
        if removed >= extra_rows:
            break
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
            removed += 1
    return removed


def _replace_treatment_note(all_texts, course_counts: Dict[str, Dict[str, int]]):
    """改寫備註的處置費計算方式。

    模板寫死「開立人數*每份處方費400元」，費率分流後會與表格金額矛盾。
    單一且為一般費率 → 不動(維持既有領據字句)。
    多費率 → 換成單行精簡句，長度控制在一行內以免把領據頂到第二頁。
    """
    labels = _active_treatment_labels(course_counts)
    if len(labels) <= 1 and (not labels or labels[0] == TREATMENT_DEFAULT_LABEL):
        return

    parts = [f"{lb} {treatment_fee_for_label(lb)} 元" for lb in labels]
    note = "處方處置費計算方式：每筆執行－" + "、".join(parts)

    for t in all_texts:
        txt = t.text or ""
        if "處方處置費計算方式" in txt:
            t.text = note
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            return


def _fill_summary_table_health_mgmt(doc, people_count: int,
                                     prescription_count: int,
                                     is_qualified: bool, total_amount: int):
    """健管費 5 欄表（給付項目/處方類型/開立處方人數/開立份數/達標 + 總計）"""
    body = doc.element.body
    target = None
    for tbl in body.iter(qn("w:tbl")):
        first_row = tbl.find(qn("w:tr"))
        if first_row is None:
            continue
        first_text = "".join(t.text or "" for t in first_row.iter(qn("w:t")))
        if "給付項目" in first_text and "達標" in first_text:
            target = tbl
            break
    if target is None:
        return

    all_rows = target.findall(qn("w:tr"))
    if len(all_rows) < 3:
        return

    r1_cells = all_rows[1].findall(qn("w:tc"))
    if len(r1_cells) >= 5:
        _set_cell_text(r1_cells[2], str(people_count) if people_count else "")
        _set_cell_text(r1_cells[3], str(prescription_count) if prescription_count else "")
        _set_cell_text(r1_cells[4], "是" if is_qualified else "否")

    # R2 cells: [gs=2]總計 | [gs=3]$金額  → 2 個 direct cell
    r2_cells = all_rows[2].findall(qn("w:tc"))
    if len(r2_cells) >= 2:
        _set_cell_text(r2_cells[1], f"${total_amount:,}" if total_amount else "")


# ============================================================
#  扣稅版：應付/代扣 2.11%/代扣所得稅/實付 nested table
# ============================================================

def _fill_tax_box_text(doc, category: str = ""):
    """依報稅類別動態改寫「代扣二代健保／所得稅」欄位的說明文字、稅率與標籤。

    模板固定寫執行業務版（20,000 / 10% / 執行業務扣稅）。依 category 改成：
      - 二代健保門檻（第 1 點數字）：執業所得 20,000 / 薪資 29,500
      - 所得稅說明（第 2 點）：執業所得「扣繳執行業務 20,000 元以上」/
                               薪資「扣繳薪資所得 90,500 元以上」
      - 稅率格：執業所得 10% / 薪資 5%
      - 標籤：執業所得「執行業務扣稅」/ 薪資「薪資所得稅」
    """
    is_salary = category == SALARY
    nhi_thr = nhi_threshold(category)                  # 20000 / 29500
    it_thr = income_tax_threshold(category)            # 20000 / 90500
    rate_pct = f"{round(income_tax_rate(category) * 100)}%"  # "10%" / "5%"
    income_kind = "薪資所得" if is_salary else "執行業務"
    income_label = "薪資所得稅" if is_salary else "執行業務扣稅"

    for t in doc.element.body.iter(qn("w:t")):
        txt = t.text or ""
        if not txt:
            continue
        # 第 1 點：二代健保門檻數字（…執行業務 XX,XXX 元(含)以上執行代扣）
        if "二代健保兼職人員給付金額達" in txt:
            t.text = re.sub(
                r"[\d,]+\s*元\(含\)以上執行代扣",
                f"{nhi_thr:,}元(含)以上執行代扣", txt)
        # 第 2 點：所得稅類別字樣 + 門檻數字
        elif re.search(r"\d\s*[.．]\s*扣繳.*以上執行代扣", txt):
            t.text = re.sub(
                r"扣繳.*?以上執行代扣",
                f"扣繳{income_kind}{it_thr:,}元以上執行代扣", txt)
        # 稅率格：把「10%」改成對應稅率（2.11% 那格不動）
        elif re.search(r"\d+(\.\d+)?\s*%", txt) and "2.11" not in txt:
            t.text = re.sub(r"\d+(\.\d+)?\s*%", rate_pct, txt)
        # 標籤格：執行業務扣稅 / 薪資所得稅（保留前後空白）
        elif txt.strip() in ("執行業務扣稅", "薪資所得稅"):
            t.text = txt.replace(txt.strip(), income_label)
        else:
            continue
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _fill_tax_amounts(doc, total_amount: int, category: str = ""):
    """填扣稅版 nested table 的「應付/代扣2.11%/代扣所得稅/實付」4 cells。

    依報稅類別（category）決定二代健保門檻（執業所得 20000 / 薪資 29500）與
    所得稅費率/門檻（執業所得 10%、>20000 / 薪資 5%、>90500）。二代健保採
    「達（含）」＝大於等於，所得稅採「超過」嚴格大於（詳見 tax_rules.withhold）。
    未達門檻該格寫「不需扣稅」。
    """
    nhi, income_tax, actual = withhold(total_amount, category)
    v_payable = f"{total_amount:,}"
    v_nhi = f"{nhi:,}" if nhi > 0 else "不需扣稅"
    v_tax = f"{income_tax:,}" if income_tax > 0 else "不需扣稅"
    v_actual = f"{actual:,}"

    body = doc.element.body
    # 鎖定 nested table（3 直接 row，且第一列含「應付金額」+「實付金額」）
    for tbl in body.iter(qn("w:tbl")):
        rows = tbl.findall(qn("w:tr"))
        if len(rows) != 3:
            continue
        first_row_text = "".join(t.text or "" for t in rows[0].iter(qn("w:t")))
        if "應付金額" not in first_row_text or "實付金額" not in first_row_text:
            continue
        cells = rows[2].findall(qn("w:tc"))
        if len(cells) >= 4:
            _set_cell_text(cells[0], v_payable)
            _set_cell_text(cells[1], v_nhi)
            _set_cell_text(cells[2], v_tax)
            _set_cell_text(cells[3], v_actual)
        return


# ============================================================
#  Cell 文字設定 / 個資填值（共用工具）
# ============================================================

def _set_cell_text(cell, text: str, ref_rPr_elem=None):
    """填空式：找 cell 第一個 w:t，把它的文字替換為 text，保留原 run / rPr / pPr。
    其他 w:t 文字清空，不刪 run（保持結構）。
    若 cell 完全沒 w:t（罕見），就在第一個 paragraph 後追加一個 run（fallback）。

    ref_rPr_elem: fallback 才會用到（建立全新 run 時）。
    """
    wts = list(cell.iter(qn("w:t")))
    if wts:
        wts[0].text = text
        wts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        for t in wts[1:]:
            t.text = ""
        return

    # Fallback：cell 內完全沒有 w:t
    import copy
    from lxml import etree

    paras = cell.findall(qn("w:p"))
    if not paras:
        p = parse_xml(f'<w:p {nsdecls("w")}/>')
        cell.append(p)
        paras = [p]
    p = paras[0]

    new_r = etree.SubElement(p, qn("w:r"))
    if ref_rPr_elem is not None:
        new_r.append(copy.deepcopy(ref_rPr_elem))
    else:
        rPr = etree.SubElement(new_r, qn("w:rPr"))
        rFonts = etree.SubElement(rPr, qn("w:rFonts"))
        rFonts.set(qn("w:ascii"), "標楷體")
        rFonts.set(qn("w:eastAsia"), "標楷體")
    new_t = etree.SubElement(new_r, qn("w:t"))
    new_t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    new_t.text = text


def _get_ref_rpr(cell):
    """取 cell 內第一個 run 的 rPr element（呼叫端會自行 deepcopy）"""
    for p in cell.findall(qn("w:p")):
        for r in p.findall(qn("w:r")):
            rPr = r.find(qn("w:rPr"))
            if rPr is not None:
                return rPr
    return None


def _fill_personal_info_xml(doc, receipt):
    """填身分證/地址/電話/銀行 等個資（掃所有層級的 paragraphs）"""
    body = doc.element.body
    FILL_MAP = [
        ("身分證",     receipt.id_number),
        ("戶籍",       receipt.address),
        ("聯絡電話",   receipt.phone),
        ("戶名",       receipt.account_name),
        ("銀行及分行", receipt.bank_branch),
        ("銀行代碼",   receipt.bank_code),
        ("帳號",       receipt.account_number),
    ]
    all_paras = list(body.iter(qn("w:p")))
    for keyword, value in FILL_MAP:
        if not value:
            continue
        for p in all_paras:
            txt = "".join(t.text or "" for t in p.iter(qn("w:t")))
            if keyword in txt:
                _fill_para_after_colon_xml(p, value)
                break


def _fill_para_after_colon_xml(p_elem, value: str):
    """段落內找「：」，把值塞在後面"""
    wts = list(p_elem.iter(qn("w:t")))
    for i, wt in enumerate(wts):
        txt = wt.text or ""
        for sep in ("：", ":"):
            if sep not in txt:
                continue
            colon_pos = txt.index(sep)
            existing_after = txt[colon_pos + 1:].strip()
            if existing_after:
                wt.text = txt[: colon_pos + 1] + value
                wt.set(
                    "{http://www.w3.org/XML/1998/namespace}space", "preserve")
            elif i + 1 < len(wts):
                wts[i + 1].text = value
                wts[i + 1].set(
                    "{http://www.w3.org/XML/1998/namespace}space", "preserve")
            else:
                wt.text = txt[: colon_pos + 1] + value
                wt.set(
                    "{http://www.w3.org/XML/1998/namespace}space", "preserve")
            return


# ============================================================
#  個資縮排：處理 body 段落 + 所有 nested table cell 段落
# ============================================================

def _fix_personal_info_indent(doc):
    """確保個資段落（具領人/身分證/戶籍/聯絡電話/戶名/銀行/帳號）長行換行
    時不會跑回頁面/cell 左邊。

    處理兩種模板情況：
    1. 舊版（個資在 body 段落，旁有 anchored image）：依圖框右緣計算 base_indent，
       設 w:left + w:hanging 形成懸掛縮排。
    2. 新版扣稅模板（個資在 table cell 內，pPr 已有 w:firstLine 指向圖框右側）：
       只是首行縮排，地址超長換行會跑到 cell 左緣。改成 w:left（所有行同位置）
       讓換行也保持在右側。
    """
    from lxml import etree

    WPD = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    CHAR_WIDTH = 360
    LEFT_OFFSET_CHARS = -1
    body = doc.element.body
    INFO_KWS = ("具領", "身分證", "戶籍", "聯絡電話", "戶名", "銀行", "帳號")

    # ---- (1) 舊版：body 段落 + anchored image ----
    indent_twips = 3240
    for p in body.findall(qn("w:p")):
        for anchor in p.iter(f"{{{WPD}}}anchor"):
            pos_h = anchor.find(f"{{{WPD}}}positionH")
            extent = anchor.find(f"{{{WPD}}}extent")
            if pos_h is None or extent is None:
                continue
            pos_off = pos_h.find(f"{{{WPD}}}posOffset")
            if pos_off is None:
                continue
            h_off_emu = int(pos_off.text or "0")
            if h_off_emu > 1_000_000:
                continue
            cx_emu = int(extent.get("cx", 0))
            right_emu = h_off_emu + cx_emu
            indent_twips = max(2000, int(right_emu / 635))
            break

    base_indent = max(1000, indent_twips - LEFT_OFFSET_CHARS * CHAR_WIDTH)

    DRAWING_TAGS = {
        qn("w:drawing"), qn("w:pict"),
        f"{{{MC_NS}}}AlternateContent",
    }

    def _in_drawing(t_elem, root_p):
        a = t_elem.getparent()
        while a is not None and a is not root_p:
            if a.tag in DRAWING_TAGS:
                return True
            a = a.getparent()
        return False

    def _body_text_before_colon(p_elem):
        parts = []
        for t in p_elem.iter(qn("w:t")):
            if _in_drawing(t, p_elem):
                continue
            parts.append(t.text or "")
        body_txt = "".join(parts)
        for sep in ("：", ":"):
            idx = body_txt.find(sep)
            if idx >= 0:
                return idx + 1
        return 0

    for p in body.findall(qn("w:p")):
        txt = "".join(t.text or "" for t in p.iter(qn("w:t")))
        if not any(kw in txt for kw in INFO_KWS):
            continue
        WPD_NS = f"{{{WPD}}}"
        for r in list(p.findall(qn("w:r"))):
            has_anchor = any(True for _ in r.iter(f"{WPD_NS}anchor"))
            if has_anchor:
                continue
            run_txt = "".join(t.text or "" for t in r.iter(qn("w:t")))
            if not run_txt:
                continue
            if run_txt.strip() == "":
                p.remove(r)
                continue
            break

        label_chars = _body_text_before_colon(p)
        label_width = label_chars * CHAR_WIDTH

        pPr = p.find(qn("w:pPr"))
        if pPr is None:
            pPr = parse_xml(f'<w:pPr {nsdecls("w")}/>')
            p.insert(0, pPr)
        ind = pPr.find(qn("w:ind"))
        if ind is None:
            ind = etree.SubElement(pPr, qn("w:ind"))
        for attr_name in ("w:firstLine", "w:firstLineChars"):
            attr_q = qn(attr_name)
            if ind.get(attr_q) is not None:
                del ind.attrib[attr_q]

        if label_width > 0:
            ind.set(qn("w:left"), str(base_indent + label_width))
            ind.set(qn("w:hanging"), str(label_width))
        else:
            ind.set(qn("w:left"), str(base_indent))
            h_q = qn("w:hanging")
            if ind.get(h_q) is not None:
                del ind.attrib[h_q]

    # ---- (2) 新版：所有段落（含 nested cell）— 設懸掛縮排 ----
    # 模板原本只設 w:firstLine（首行縮排），地址過長換行會跑到頁面左緣。
    # 改成懸掛縮排：第一行對齊 firstLine 位置（圖框右側），換行對齊「冒號後第一字」。
    #   w:left   = base + label_width（換行位置）
    #   w:hanging= label_width（首行往左退 label_width，回到 base）
    CELL_CHAR_WIDTH = 320  # 中文字寬：16pt 標楷體 = 320 twips（個資段落實際字級）
    for p in body.iter(qn("w:p")):
        txt = "".join(t.text or "" for t in p.iter(qn("w:t")))
        if not any(kw in txt for kw in INFO_KWS):
            continue
        pPr = p.find(qn("w:pPr"))
        if pPr is None:
            continue
        ind = pPr.find(qn("w:ind"))
        if ind is None:
            continue
        first_line = ind.get(qn("w:firstLine"))
        first_line_chars = ind.get(qn("w:firstLineChars"))
        left_attr = ind.get(qn("w:left"))
        if not (first_line and not left_attr):
            continue
        # 算 label 寬度（冒號前的字數，含冒號）— 不算 drawing 內的文字
        # （例如「具領人用印」的 alt-content 文字被 anchor 包住，會誤計）
        body_txt_parts = []
        for tt in p.iter(qn("w:t")):
            if _in_drawing(tt, p):
                continue
            body_txt_parts.append(tt.text or "")
        body_only_txt = "".join(body_txt_parts)
        label_chars = 0
        for sep in ("：", ":"):
            idx = body_only_txt.find(sep)
            if idx >= 0:
                label_chars = idx + 1
                break
        label_width = label_chars * CELL_CHAR_WIDTH
        base_indent = int(first_line)

        # 不保留 leftChars / firstLineChars：chars 單位會依「平均字寬」算，
        # 含中英數混排時會比 twips 值小，造成首字被「具領人用印」圖框蓋住。
        del ind.attrib[qn("w:firstLine")]
        if first_line_chars is not None:
            del ind.attrib[qn("w:firstLineChars")]

        if label_width > 0:
            ind.set(qn("w:left"), str(base_indent + label_width))
            ind.set(qn("w:hanging"), str(label_width))
        else:
            ind.set(qn("w:left"), str(base_indent))
