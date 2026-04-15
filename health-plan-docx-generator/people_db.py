"""人員個資資料庫 — 從 Excel 讀取/建立個人資料查找表

Excel 格式（第一列為欄位名稱）：
    姓名 | 身分證字號 | 戶籍地址 | 聯絡電話 | 戶名 | 銀行及分行 | 銀行代碼 | 帳號

用法：
    lookup = load_people_db("人員個資.xlsx")
    # lookup == {"王永良": ReceiptInfo(...)}
"""

import os
import openpyxl
from models import ReceiptInfo

COLUMNS = ["姓名", "身分證字號", "戶籍地址", "聯絡電話", "戶名", "銀行及分行", "銀行代碼", "帳號"]

FIELD_MAP = {
    "姓名":     "recipient_name",
    "身分證字號": "id_number",
    "戶籍地址":  "address",
    "聯絡電話":  "phone",
    "戶名":     "account_name",
    "銀行及分行": "bank_branch",
    "銀行代碼":  "bank_code",
    "帳號":     "account_number",
}


def create_template(path: str):
    """建立空白個資範本 Excel"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "人員個資"

    # 欄位標題
    for col, name in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=col, value=name)
        cell.font = openpyxl.styles.Font(bold=True)

    # 欄寬
    widths = [10, 14, 30, 14, 10, 20, 10, 20]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = w

    # 範例資料（第二列）
    ws.append(["王永良", "A123456789", "台北市中山區中山北路一段1號",
                "02-1234-5678", "王永良", "台灣銀行中山分行", "004", "123456789012"])

    wb.save(path)
    pass


def export_to_db(lookup: dict, path: str, overwrite: bool = False):
    """將 ReceiptInfo lookup 寫入個資 Excel
    overwrite=False：只補缺漏欄位（不覆蓋已有資料）
    overwrite=True ：完全覆蓋同名人員
    """
    # 讀取現有資料（若檔案存在）
    existing = load_people_db(path) if (os.path.exists(path) and not overwrite) else {}

    # 合併：新資料補入，已有資料保留
    merged = dict(existing)
    for name, info in lookup.items():
        if name not in merged:
            merged[name] = info
        elif not overwrite:
            # 只補空白欄位
            old = merged[name]
            from dataclasses import replace
            merged[name] = replace(
                old,
                id_number=old.id_number or info.id_number,
                address=old.address or info.address,
                phone=old.phone or info.phone,
                account_name=old.account_name or info.account_name,
                bank_branch=old.bank_branch or info.bank_branch,
                bank_code=old.bank_code or info.bank_code,
                account_number=old.account_number or info.account_number,
            )
        else:
            merged[name] = info

    # 建立新 Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "人員個資"

    for col, name in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=col, value=name)
        cell.font = openpyxl.styles.Font(bold=True)

    widths = [10, 14, 30, 14, 10, 20, 10, 20]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = w

    for row_idx, (name, info) in enumerate(sorted(merged.items()), 2):
        ws.cell(row=row_idx, column=1, value=name)
        ws.cell(row=row_idx, column=2, value=info.id_number or "")
        ws.cell(row=row_idx, column=3, value=info.address or "")
        ws.cell(row=row_idx, column=4, value=info.phone or "")
        ws.cell(row=row_idx, column=5, value=info.account_name or "")
        ws.cell(row=row_idx, column=6, value=info.bank_branch or "")
        ws.cell(row=row_idx, column=7, value=info.bank_code or "")
        ws.cell(row=row_idx, column=8, value=info.account_number or "")

    wb.save(path)
    return len(merged)


def load_people_db(path: str) -> dict[str, ReceiptInfo]:
    """讀取個資 Excel，回傳 {姓名: ReceiptInfo}"""
    if not path or not os.path.exists(path):
        return {}

    try:
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
    except Exception:
        return {}

    # 讀欄位名稱對應位置
    headers = {}
    for cell in ws[1]:
        if cell.value and str(cell.value).strip() in FIELD_MAP:
            headers[str(cell.value).strip()] = cell.column - 1  # 0-based index

    if "姓名" not in headers:
        return {}

    lookup: dict[str, ReceiptInfo] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        name_idx = headers["姓名"]
        if name_idx >= len(row):
            continue
        name = str(row[name_idx]).strip() if row[name_idx] else ""
        if not name or name == "None":
            continue

        info = ReceiptInfo(recipient_name=name)
        for col_name, field in FIELD_MAP.items():
            if col_name == "姓名" or col_name not in headers:
                continue
            idx = headers[col_name]
            if idx < len(row) and row[idx] is not None:
                setattr(info, field, str(row[idx]).strip())

        lookup[name] = info

    return lookup
