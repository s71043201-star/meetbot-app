"""產生「領據填寫範例.pdf」:
1. 用實際模板 generate_receipt 產生空白扣稅領據(個資全空、用範例金額)
2. 透過 Word COM 轉 PDF
3. 用 PyMuPDF 在 PDF 上加紅框 + 紅字註解
4. 覆蓋 word_templates/領據填寫範例.pdf
"""
import os
import re
import sys
import tempfile

import fitz  # PyMuPDF
from docx import Document

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from models import ReceiptInfo
from templates.receipt import generate_receipt


OUTPUT_PDF = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "word_templates", "領據填寫範例.pdf",
)


def replace_digits_in_docx(docx_path: str):
    """把 docx 中所有數字字元改成 X(讓範例變成全空白模板)。"""
    doc = Document(docx_path)

    def fix_runs(paragraphs):
        for para in paragraphs:
            for run in para.runs:
                new = re.sub(r"\d", "X", run.text)
                if new != run.text:
                    run.text = new

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                fix_runs(cell.paragraphs)
                for inner_table in cell.tables:
                    for ir in inner_table.rows:
                        for ic in ir.cells:
                            fix_runs(ic.paragraphs)
    fix_runs(doc.paragraphs)

    doc.save(docx_path)


def docx_to_pdf(docx_path: str, pdf_path: str):
    import win32com.client
    word = win32com.client.DispatchEx("Word.Application")
    try:
        word.Visible = False
        word.DisplayAlerts = 0
    except Exception:
        pass
    try:
        doc = word.Documents.Open(os.path.abspath(docx_path))
        doc.SaveAs(os.path.abspath(pdf_path), FileFormat=17)
        doc.Close(SaveChanges=0)
    finally:
        word.Quit()


CN_FONT_PATH = r"C:\Windows\Fonts\msjhbd.ttc"  # Microsoft JhengHei Bold
if not os.path.exists(CN_FONT_PATH):
    CN_FONT_PATH = r"C:\Windows\Fonts\msjh.ttc"


def add_red_annotations(pdf_in: str, pdf_out: str):
    """在 PDF 上找 label 位置,加紅框 + 紅字註解。"""
    doc = fitz.open(pdf_in)
    page = doc[0]
    page.insert_font(fontname="cjk", fontfile=CN_FONT_PATH)

    PAGE_W = page.rect.x1
    RED = (0.86, 0.10, 0.10)
    LIGHT_RED = (1.0, 0.95, 0.95)

    def draw_red(rect: fitz.Rect, width_pt: float = 1.4,
                 dashes: str = ""):
        page.draw_rect(rect, color=RED, width=width_pt,
                       dashes=dashes)

    def red_text(x: float, y: float, text: str, size: float = 9):
        page.insert_text((x, y), text, fontsize=size,
                         color=RED, fontname="cjk")

    # ── 個資 8 個欄位:用「不帶冒號」label 找,在 label 右邊畫紅框 ──
    # field tuples: (search_label, note, box_width, x_offset_after_label)
    fields = [
        ("具領人",   "請寫領款人全名"),
        ("身分證字號","請寫領款人身分證字號"),
        ("戶籍地址", "請寫領款人戶籍地址"),
        ("聯絡電話", "請寫領款人個人連絡電話"),
        ("戶名",     "請寫領款人個人帳戶戶名"),
        ("銀行及分行","請寫領款人個人帳戶銀行及分行名"),
        ("銀行代碼", "請寫領款人個人帳戶銀行代碼"),
        ("帳號",     "請寫領款人個人帳戶銀行帳號"),
    ]
    field_rects: list[fitz.Rect] = []
    for label, note in fields:
        rs = page.search_for(label)
        if not rs:
            continue
        r = rs[0]
        # label 後通常接全形冒號 + 內容 — 跳過冒號 ~14pt 後開始紅框
        x0 = r.x1 + 14
        # 紅框延伸到頁面 80% 處
        x1 = PAGE_W * 0.78
        rect = fitz.Rect(x0, r.y0 - 1, x1, r.y1 + 1)
        draw_red(rect)
        field_rects.append(rect)
        # 註解放紅框右邊
        red_text(x1 + 4, r.y1 - 1, note, size=8.5)

    # ── 用「個資區大外框」包住所有 8 個欄位 ──
    if field_rects:
        outer = fitz.Rect(
            min(r.x0 for r in field_rects) - 60,
            min(r.y0 for r in field_rects) - 6,
            max(r.x1 for r in field_rects) + 4,
            max(r.y1 for r in field_rects) + 6,
        )
        # 虛線外框
        draw_red(outer, width_pt=1.6, dashes="[3 2] 0")
        # 右上角紅色提示文字
        red_text(outer.x1 - 240, outer.y0 - 4,
                 "★ 如有缺漏需補寫資料", size=10)

    # ── 「具領人用印」框內加紅字說明(分兩行,擺在 label 下方框中) ──
    sig_rects = page.search_for("具領人用印")
    if sig_rects:
        sr = sig_rects[0]
        # 「具領人用印」label 下方 ~16pt / 30pt 兩行,框中央
        red_text(sr.x0 - 4, sr.y1 + 18, "請親自簽名", size=9)
        red_text(sr.x0 - 4, sr.y1 + 32, "或蓋個人私章", size=9)

    # ── 頁面最底加大字紅字提示「請檢附存摺影本」 ──
    red_text(40, page.rect.y1 - 22,
             "★ 請記得檢附存摺影本,需與上面填寫資訊相同",
             size=14)

    # ── 中華民國 年 月 日 整列紅框(留邊距,避免超出頁面)──
    rocs = page.search_for("中華民國")
    if rocs:
        r = rocs[0]
        # 紅框寬度限制在頁面 75% 處,讓註解能放右側
        date_rect = fitz.Rect(r.x0 - 4, r.y0 - 2,
                              PAGE_W * 0.75, r.y1 + 2)
        draw_red(date_rect)
        red_text(date_rect.x1 + 6, date_rect.y1 - 2,
                 "請填寫今日日期", size=9)

    # ── 頁首裝飾橫幅 ──
    banner = fitz.Rect(20, 6, PAGE_W - 20, 28)
    page.draw_rect(banner, color=RED, fill=LIGHT_RED, width=1.2)
    red_text(28, 21,
             "★ 領據填寫範例 ── 紅框處為需要您手動填寫的欄位,"
             "其餘已由系統自動代入",
             size=9.5)

    doc.save(pdf_out)
    doc.close()


def main():
    # 1. 產空白扣稅領據 docx (用 amount=29500 觸發扣稅顯示)
    empty = ReceiptInfo(
        recipient_name="",
        id_number="",
        address="",
        phone="",
        account_name="",
        bank_branch="",
        bank_code="",
        account_number="",
        amount=29500,
    )
    tmp_dir = tempfile.mkdtemp(prefix="receipt_template_")
    docx_path = os.path.join(tmp_dir, "範例.docx")
    pdf_raw = os.path.join(tmp_dir, "範例_raw.pdf")

    generate_receipt(
        empty, 115, 4, docx_path,
        fee_type="運動、營養、情緒調適、社會處方處方費",
        presc_counts={"運動處方": 19, "營養處方": 19,
                      "社會處方": 19, "情緒調適處方": 19},
        exec_counts={"運動處方": 19, "營養處方": 18,
                     "社會處方": 14, "情緒調適處方": 16},
        fee_per_presc=300,
        fee_per_exec=100,
    )
    print(f"[1/4] 產生空白領據 docx → {docx_path}")

    # 1.5 把所有數字改成 X(讓範例完全空白)
    replace_digits_in_docx(docx_path)
    print(f"[2/4] 數字 → X 替換完成")

    # 2. 轉 PDF
    docx_to_pdf(docx_path, pdf_raw)
    print(f"[3/4] 轉 PDF → {pdf_raw}")

    # 3. 加紅框註解
    add_red_annotations(pdf_raw, OUTPUT_PDF)
    print(f"[4/4] 加紅框 → {OUTPUT_PDF}")


if __name__ == "__main__":
    main()
