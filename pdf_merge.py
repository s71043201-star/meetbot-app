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


def normalize_id_number(raw: str) -> str:
    """身分證字號正規化：去除前後空白、轉大寫；空字串視為無效。"""
    if not raw:
        return ""
    return str(raw).strip().upper()


def merge_pdfs_encrypted(
    pdf_paths: list[str],
    output_path: str,
    user_password: str | None = None,
    owner_password: str | None = None,
):
    """合併多個 PDF；若提供 user_password 則加密。

    user_password 留空 → 不加密，行為等同 merge_pdfs。
    owner_password 留空 → 退回使用 user_password（PyPDF2 預設）。
    當 user_password 留空但 owner_password 有值時，仍視為不加密
    （PDF 規格不允許只設 owner_password）。
    """
    import os
    import tempfile
    from PyPDF2 import PdfMerger, PdfReader, PdfWriter

    merger = PdfMerger()
    for path in pdf_paths:
        merger.append(path)

    if not user_password:
        merger.write(output_path)
        merger.close()
        return

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(tmp_fd)
    try:
        merger.write(tmp_path)
        merger.close()

        reader = PdfReader(tmp_path)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(
            user_password=user_password,
            owner_password=owner_password or user_password,
            use_128bit=True,
        )
        with open(output_path, "wb") as f:
            writer.write(f)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
