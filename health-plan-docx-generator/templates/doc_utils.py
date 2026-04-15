from docx import Document
from docx.shared import Pt, Cm, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml
import datetime


def create_document(landscape: bool = True) -> Document:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "標楷體"
    style.font.size = Pt(12)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "標楷體")
    # 段落間距歸零，與原始範本一致
    style.paragraph_format.space_before = Pt(0)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.line_spacing = 1.0

    sections = doc.sections
    for section in sections:
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(2.54)
        section.right_margin = Cm(2.54)
        if landscape:
            section.page_width = Cm(29.7)
            section.page_height = Cm(21)
            section.orientation = 1  # LANDSCAPE
        else:
            section.page_width = Cm(21)
            section.page_height = Cm(29.7)
            section.orientation = 0  # PORTRAIT

    return doc


def add_run(paragraph, text: str, size: int = 12, bold: bool = False):
    run = paragraph.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = "標楷體"
    run.element.rPr.rFonts.set(qn("w:eastAsia"), "標楷體")
    return run


def compact_paragraph(p):
    """設定段落為緊湊間距（段前段後 0，單行間距）"""
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.0


def add_title(doc: Document, text: str, size: int = 20):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    compact_paragraph(p)
    add_run(p, text, size=size, bold=True)
    return p


def set_cell_text(cell, text: str, bold: bool = False, align: str = "center",
                  font_size: int = 16):
    cell.text = ""
    p = cell.paragraphs[0]
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == "right":
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    else:
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(str(text))
    run.bold = bold
    run.font.size = Pt(font_size)
    run.font.name = "標楷體"
    run.element.rPr.rFonts.set(qn("w:eastAsia"), "標楷體")
    # Vertical center
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    vAlign = parse_xml(f'<w:vAlign {nsdecls("w")} w:val="center"/>')
    tcPr.append(vAlign)


def set_table_borders(table):
    tbl = table._tbl
    tblPr = tbl.tblPr if tbl.tblPr is not None else parse_xml(
        f'<w:tblPr {nsdecls("w")}/>'
    )
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        '  <w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '  <w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '  <w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '  <w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '  <w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '  <w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        "</w:tblBorders>"
    )
    tblPr.append(borders)


def set_col_widths(table, widths_emu: list):
    for row in table.rows:
        for i, w in enumerate(widths_emu):
            row.cells[i].width = w


def add_info_table(doc, fields: list[tuple[str, str]],
                   col_widths=None, font_size: int = 16):
    """Info block: 醫療機構/申報期間/開立醫師 etc."""
    table = doc.add_table(rows=len(fields), cols=2)
    set_table_borders(table)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    for i, (label, value) in enumerate(fields):
        set_cell_text(table.cell(i, 0), label, bold=True, align="left",
                      font_size=font_size)
        set_cell_text(table.cell(i, 1), value, align="left",
                      font_size=font_size)
    # 欄寬與實際範本一致：69.3mm / 180.8mm
    set_col_widths(table, col_widths or [2493000, 6503000])
    return table


def add_page_break(doc: Document):
    doc.add_page_break()


def today_roc() -> tuple[int, int, int]:
    today = datetime.date.today()
    return today.year - 1911, today.month, today.day


def add_signature_line(doc: Document, label: str = "確認簽章"):
    p = doc.add_paragraph()
    compact_paragraph(p)
    add_run(p, f"{label}: _____________________ ", size=18)


def add_date_line(doc: Document, year: int, month: int, day: int):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    compact_paragraph(p)
    add_run(p, f"產表日期：{year} 年 {month} 月 {day} 日")


def add_note(doc: Document, lines: list[str], font_size: int = 16):
    p = doc.add_paragraph()
    compact_paragraph(p)
    add_run(p, "註", size=font_size, bold=True)
    add_run(p, ":", size=font_size, bold=True)
    for i, line in enumerate(lines, 1):
        p = doc.add_paragraph()
        compact_paragraph(p)
        add_run(p, f"{i}. {line}", size=font_size)
