"""Word 轉 PDF + 合併多個 PDF"""

import os


def docx_to_pdf(docx_path: str, pdf_path: str):
    """用 Word COM 轉 PDF（最大相容性）"""
    import win32com.client
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(os.path.abspath(docx_path))
        doc.SaveAs(os.path.abspath(pdf_path), FileFormat=17)  # 17 = PDF
        doc.Close()
    finally:
        word.Quit()


def docx_to_pdf_batch(docx_paths: list[str], pdf_paths: list[str]):
    """批次轉換，共用一個 Word instance（快很多）"""
    import win32com.client
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        for docx_path, pdf_path in zip(docx_paths, pdf_paths):
            doc = word.Documents.Open(os.path.abspath(docx_path))
            doc.SaveAs(os.path.abspath(pdf_path), FileFormat=17)
            doc.Close()
    finally:
        word.Quit()


def merge_pdfs(pdf_paths: list[str], output_path: str):
    """合併多個 PDF 為一個"""
    from PyPDF2 import PdfMerger
    merger = PdfMerger()
    for path in pdf_paths:
        merger.append(path)
    merger.write(output_path)
    merger.close()
