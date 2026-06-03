"""人員個資資料庫 — 從 Excel 讀取/建立個人資料查找表

Excel 格式（第一列為欄位名稱）：
    姓名 | 身分證字號 | 戶籍地址 | 聯絡電話 | 戶名 | 銀行及分行 | 銀行代碼 | 帳號 | Email

用法：
    lookup = load_people_db("人員個資.xlsx")
    # lookup == {"王永良": ReceiptInfo(...)}
"""

import os
import openpyxl
from models import ReceiptInfo

COLUMNS = ["姓名", "角色", "所屬診所", "身分證字號", "戶籍地址", "聯絡電話", "戶名", "銀行及分行", "銀行代碼", "帳號", "Email", "身分別"]

FIELD_MAP = {
    "姓名":     "recipient_name",
    "角色":     "role",
    "身分別":    "occupation",   # 報稅類別判斷：醫師/營養師/藥師/護理師/運動教練/大學社大老師
    "職業":     "occupation",   # 別名
    "所屬診所":  "clinic_name",
    "身分證字號": "id_number",
    "戶籍地址":  "address",
    "聯絡電話":  "phone",
    "戶名":     "account_name",
    "銀行及分行": "bank_branch",
    "銀行代碼":  "bank_code",
    "分行代號":  "bank_code",   # 別名：7 碼銀行+分行代號 (XXX-XXXX)
    "帳號":     "account_number",
    "Email":    "email",
}


def _cell_str(v) -> str:
    """將 Excel 儲存格值轉為乾淨字串。
    數字型帳號/電話/身分證會被 openpyxl 讀成 float（如 721168845196.0），
    若直接 str() 會多出 .0；此處整數值的 float 先轉 int 再轉字串。
    """
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


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
    widths = [10, 10, 20, 14, 30, 14, 10, 20, 10, 20, 28, 12]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = w

    # 範例資料（第二列）
    ws.append(["王永良", "醫師", "", "A123456789", "台北市中山區中山北路一段1號",
                "02-1234-5678", "王永良", "台灣銀行中山分行", "004", "123456789012",
                "wang@example.com", "醫師"])
    ws.append(["周建青", "診所行政人員", "何叔芳小兒科診所", "", "",
                "", "周建青", "", "", "", "", ""])
    ws.append(["林營養", "課程老師", "", "B123456789", "台北市…",
                "", "林營養", "玉山銀行", "808", "0987654321", "", "營養師"])
    # 備註列：角色說明
    note_row = ws.max_row + 1
    ws.cell(row=note_row, column=1,
            value="※ 角色：醫師 / 課程老師 / 診所行政人員　｜　身分別僅需區分營養師(執業所得)與其他課程老師(薪資)，診所行政固定7000免填")
    ws.cell(row=note_row, column=1).font = openpyxl.styles.Font(color="808080", italic=True)

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
                role=info.role or old.role,
                clinic_name=info.clinic_name or old.clinic_name,
                id_number=old.id_number or info.id_number,
                address=old.address or info.address,
                phone=old.phone or info.phone,
                account_name=old.account_name or info.account_name,
                bank_branch=old.bank_branch or info.bank_branch,
                bank_code=old.bank_code or info.bank_code,
                account_number=old.account_number or info.account_number,
                email=old.email or info.email,
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

    widths = [10, 10, 20, 14, 30, 14, 10, 20, 10, 20, 28, 12]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = w

    for row_idx, (name, info) in enumerate(
            sorted(merged.items(), key=lambda x: (x[1].role or "", x[0])), 2):
        ws.cell(row=row_idx, column=1, value=name)
        ws.cell(row=row_idx, column=2, value=info.role or "")
        ws.cell(row=row_idx, column=3, value=info.clinic_name or "")
        ws.cell(row=row_idx, column=4, value=info.id_number or "")
        ws.cell(row=row_idx, column=5, value=info.address or "")
        ws.cell(row=row_idx, column=6, value=info.phone or "")
        ws.cell(row=row_idx, column=7, value=info.account_name or "")
        ws.cell(row=row_idx, column=8, value=info.bank_branch or "")
        ws.cell(row=row_idx, column=9, value=info.bank_code or "")
        ws.cell(row=row_idx, column=10, value=info.account_number or "")
        ws.cell(row=row_idx, column=11, value=info.email or "")
        ws.cell(row=row_idx, column=12, value=info.occupation or "")

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
        # 容錯：第一欄為姓名但標題列空白/未命名（常見於匯出檔），
        # 仍將第一欄視為姓名，避免整份個資讀不到。
        first = ws.cell(1, 1).value
        if first is None or not str(first).strip():
            headers["姓名"] = 0
        else:
            return {}

    lookup: dict[str, ReceiptInfo] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        name_idx = headers["姓名"]
        if name_idx >= len(row):
            continue
        name = _cell_str(row[name_idx]) if row[name_idx] else ""
        if name == "None":
            name = ""

        # 取所屬診所（用來支援「姓名空白但有診所」的列）
        clinic_val = ""
        if "所屬診所" in headers:
            cidx = headers["所屬診所"]
            if cidx < len(row) and row[cidx]:
                clinic_val = _cell_str(row[cidx])

        # 完全空白（連所屬診所都沒）才跳過
        if not name and not clinic_val:
            continue

        info = ReceiptInfo(recipient_name=name)
        for col_name, field in FIELD_MAP.items():
            if col_name == "姓名" or col_name not in headers:
                continue
            idx = headers[col_name]
            if idx < len(row) and row[idx] is not None:
                setattr(info, field, _cell_str(row[idx]))

        if name:
            lookup[name] = info
        else:
            # 「姓名空白但有所屬診所」：用特殊 key 存放，
            # 健管費領據查找時會以 clinic_name 匹配，姓名留空白。
            lookup[f"__clinic_only:{clinic_val}"] = info

    return lookup
