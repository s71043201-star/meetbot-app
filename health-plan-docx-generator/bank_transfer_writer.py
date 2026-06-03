"""富邦整批轉帳 / 整批匯款上傳檔產生器

依核銷流程算出的領取人（醫師處方費+執行費、診所健管費、課程老師處置費），
依銀行代碼分流到附檔範本（富邦匯款範本.xlsm）的兩個工作頁並「填空」：

  工作頁1「臺幣_整批轉帳」：富邦帳戶（轉入行庫代碼固定 012）
      C 轉入帳號 = 帳號 / D 轉帳金額 = 金額 / E 帳戶暱稱 = 領據戶名
  工作頁2「臺幣_整批匯款」：非富邦帳戶
      A 收款行代號 = 銀行代碼 / B 收款人帳號 = 帳號 / C 金額 = 金額 / D 收款人姓名 = 領據姓名

原則：
  - 只填空白格，不更動 區別碼(A=C/H)、轉入行庫代碼(B=012)、匯款人姓名(E)、表格格式。
  - 交易明細留言中的月份隨核銷月份填寫。
  - 自動填 H 彙總列的總筆數 / 總金額；預訂交易日期留白由人工填。
  - 缺帳號 / 缺銀行代碼者跳過並回報，不寫入。
"""

import os
from copy import copy
from dataclasses import dataclass

import openpyxl

from config import HEALTH_MGMT_FEE
from models import ReceiptInfo
from templates.executor import find_clinic_admin
from tax_rules import withhold, category_for

FUBON_BANK_CODE = "012"

SHEET_FUBON = "臺幣_整批轉帳"   # 富邦帳戶間整批轉帳
SHEET_OTHER = "臺幣_整批匯款"   # 跨行整批匯款
SHEET_TAX = "報稅基本資料"      # 第三頁：報稅清單
SHEET_MISSING = "缺帳戶清單"    # 缺帳號/代碼者：仍記金額與總計，待補帳戶

# 明細列起始（標頭在第 5 列；彙總 H 列在第 4 列）
DETAIL_START_ROW = 6
SUMMARY_ROW = 4
TAX_START_ROW = 2  # 報稅頁資料列起始（第 1 列為標頭）


@dataclass
class BankPayee:
    """一筆匯款對象（對應一張領據）"""
    name: str            # 領據姓名（收款人姓名）
    role: str            # 醫師 / 診所行政人員 / 課程老師
    amount: int          # 實付（扣繳後，實際匯款數）
    account_name: str = ""    # 戶名（富邦頁帳戶暱稱）
    bank_code: str = ""       # 銀行代碼
    account_number: str = ""  # 帳號
    bank_branch: str = ""     # 銀行及分行（輔助判斷富邦）
    gross: int = 0            # 給付總額（未扣稅，報稅頁金額）
    category: str = ""        # 報稅類別（執業所得 / 薪資）
    id_number: str = ""       # 身分證字號（報稅頁）
    address: str = ""         # 戶籍地址（報稅頁）


def _digits(s) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _is_fubon(p: BankPayee) -> bool:
    """判斷是否為富邦帳戶。

    依領據「銀行及分行」名稱含「富邦」為主要判斷（戶名只是人名，不含銀行名）；
    並以「分行代號」前三碼 012（富邦銀行代碼）為輔助判斷。
    """
    if "富邦" in (p.bank_branch or ""):
        return True
    if _digits(p.bank_code)[:3] == FUBON_BANK_CODE:
        return True
    return False


def _info_get(info, attr):
    return (getattr(info, attr, "") or "").strip() if info else ""


def _payee(name, role, gross_amount, info, *, net=None,
           category=None) -> BankPayee:
    """建立匯款對象。

    amount 一律存「實付」（扣繳後，與領據實付金額一致）：
      - net 為 None：依報稅類別套用 tax_rules.withhold 計算（主流程用）
      - net 有給值：直接採用（獨立工具由領據讀回實付時用）
    category 未給則依 info.occupation / role 判定。
    """
    g = int(gross_amount or 0)
    cat = category or category_for(_info_get(info, "occupation"), role)
    if net is None:
        _, _, net = withhold(g, cat)
    return BankPayee(
        name=(name or "").strip(),
        role=role,
        amount=int(net),
        account_name=_info_get(info, "account_name"),
        bank_code=_info_get(info, "bank_code"),
        account_number=_info_get(info, "account_number"),
        bank_branch=_info_get(info, "bank_branch"),
        gross=g,
        category=cat,
        id_number=_info_get(info, "id_number"),
        address=_info_get(info, "address"),
    )


def collect_scope_payees(acc: list, data, receipt_lookup: dict | None,
                         prod_exec: bool):
    """從一個 scope 的（已篩選）資料收集匯款對象，append 進 acc。

    與領據產生邏輯一致的金額來源：
      醫師   = prescription_fee + execution_fee
      診所   = 達標時 HEALTH_MGMT_FEE（具領人/帳戶用 find_clinic_admin）
      課程老師 = executor.receipt.amount（帳戶優先 receipt，再 fallback 個資檔）
    課程老師只在 prod_exec=True 的 scope 收集，避免跨 scope 重複。
    """
    receipt_lookup = receipt_lookup or {}

    # ── 醫師：處方費 + 處方執行費 ──
    for d in data.doctors:
        amt = (d.prescription_fee or 0) + (d.execution_fee or 0)
        if amt <= 0:
            continue
        info = receipt_lookup.get(d.doctor_name)
        acc.append(_payee(d.doctor_name, "醫師", amt, info))

    # ── 診所行政人員：健康管理費 ──
    for hm in data.health_mgmts:
        if not hm.is_qualified:
            continue
        recipient, info = find_clinic_admin(receipt_lookup,
                                            hm.medical_institution)
        name = recipient or hm.clinic_person or hm.medical_institution
        acc.append(_payee(name, "診所行政人員", HEALTH_MGMT_FEE, info))

    # ── 課程老師：處方處置費 ──
    if prod_exec:
        for ex in data.executors:
            if not ex.receipt or (ex.receipt.amount or 0) <= 0:
                continue
            name = ex.executor_name
            # 帳戶/個資：優先 executor.receipt，缺漏再用個資檔補（與領據產生一致）
            lk = receipt_lookup.get(name)
            merged = ReceiptInfo(
                account_name=_info_get(ex.receipt, "account_name") or _info_get(lk, "account_name"),
                bank_code=_info_get(ex.receipt, "bank_code") or _info_get(lk, "bank_code"),
                account_number=_info_get(ex.receipt, "account_number") or _info_get(lk, "account_number"),
                bank_branch=_info_get(ex.receipt, "bank_branch") or _info_get(lk, "bank_branch"),
                occupation=_info_get(ex.receipt, "occupation") or _info_get(lk, "occupation"),
                id_number=_info_get(ex.receipt, "id_number") or _info_get(lk, "id_number"),
                address=_info_get(ex.receipt, "address") or _info_get(lk, "address"),
            )
            acc.append(_payee(name, "課程老師", ex.receipt.amount, merged))


def _dedupe(payees: list) -> list:
    """同一(角色,姓名,帳號)合併並加總金額，避免跨機構/scope 重複匯款。
    帳號不同視為不同帳戶，分開列。順序保留首次出現。
    """
    order = []
    merged = {}
    for p in payees:
        key = (p.role, p.name, _digits(p.account_number))
        if key in merged:
            merged[key].amount += p.amount
            merged[key].gross += p.gross
        else:
            merged[key] = p
            order.append(key)
    return [merged[k] for k in order]


def _copy_row_style(ws, src_row: int, dst_row: int, max_col: int):
    for c in range(1, max_col + 1):
        s = ws.cell(src_row, c)
        d = ws.cell(dst_row, c)
        if s.has_style:
            d.font = copy(s.font)
            d.border = copy(s.border)
            d.fill = copy(s.fill)
            d.alignment = copy(s.alignment)
            d.number_format = s.number_format
            d.protection = copy(s.protection)


def _fill_fubon_sheet(ws, payees: list, month: int):
    """工作頁1：富邦整批轉帳。回傳 (筆數, 總金額)。"""
    memo_out = f"{month}月處方富邦"     # 交易明細留言(轉出存摺附註)
    memo_in = f"深耕計畫{month}月"      # 交易明細留言(轉入存摺附註)
    last_prefilled = ws.max_row
    n = len(payees)

    for i, p in enumerate(payees):
        r = DETAIL_START_ROW + i
        if r > last_prefilled:
            _copy_row_style(ws, DETAIL_START_ROW, r, ws.max_column)
        # 固定欄位（不更動既有值，僅在新增列補上）
        ws.cell(r, 1, "C")            # 區別碼
        ws.cell(r, 2, "012")          # 轉入行庫代碼（富邦）
        ws.cell(r, 6, memo_out)       # F 交易明細留言（轉出）
        ws.cell(r, 9, memo_in)        # I 交易明細留言（轉入）
        # 填空欄位
        ws.cell(r, 3, str(p.account_number))               # C 轉入帳號
        ws.cell(r, 4, p.amount)                            # D 轉帳金額
        ws.cell(r, 5, p.account_name or p.name)            # E 帳戶暱稱(戶名)

    # 其餘預填但無資料的列：僅同步留言月份（保持與範本一致，不刪除）
    for r in range(DETAIL_START_ROW + n, last_prefilled + 1):
        ws.cell(r, 6, memo_out)
        ws.cell(r, 9, memo_in)

    total = sum(p.amount for p in payees)
    ws.cell(SUMMARY_ROW, 3, n)        # C4 總筆數
    ws.cell(SUMMARY_ROW, 4, total)    # D4 總金額
    return n, total


def _fill_other_sheet(ws, payees: list, month: int):
    """工作頁2：跨行整批匯款。回傳 (筆數, 總金額)。"""
    memo = f"深耕計畫{month}月"        # F 交易明細留言(存摺附註)
    remitter = "社團法人台北市醫師公會"  # E 匯款人姓名（固定）
    last_prefilled = ws.max_row
    n = len(payees)

    for i, p in enumerate(payees):
        r = DETAIL_START_ROW + i
        if r > last_prefilled:
            _copy_row_style(ws, DETAIL_START_ROW, r, ws.max_column)
        ws.cell(r, 5, remitter)        # E 匯款人姓名（不更動既有值，新列補上）
        ws.cell(r, 6, memo)            # F 交易明細留言
        # 填空欄位
        ws.cell(r, 1, _digits(p.bank_code))   # A 收款行代號
        ws.cell(r, 2, str(p.account_number))  # B 收款人帳號
        ws.cell(r, 3, p.amount)               # C 金額
        ws.cell(r, 4, p.name)                 # D 收款人姓名（領據姓名）

    for r in range(DETAIL_START_ROW + n, last_prefilled + 1):
        ws.cell(r, 6, memo)

    total = sum(p.amount for p in payees)
    ws.cell(SUMMARY_ROW, 1, n)         # A4 總筆數
    ws.cell(SUMMARY_ROW, 3, total)     # C4 總金額
    return n, total


def _fill_tax_sheet(ws, payees: list):
    """第三頁「報稅基本資料」：填每人 身分證/姓名/戶籍地址/類別/金額(給付總額)。

    A 身分證字號 / B 姓名 / C 戶籍地址 / D 類別 / E 金額。
    右側 G~I 職業對照表（參考用）不更動。金額用給付總額（未扣稅）。
    """
    ref_row = TAX_START_ROW
    for i, p in enumerate(payees):
        r = TAX_START_ROW + i
        if r > ws.max_row:
            _copy_row_style(ws, ref_row, r, 5)  # 只複製 A~E 樣式
        ws.cell(r, 1, p.id_number)            # A 身分證字號
        ws.cell(r, 2, p.name)                 # B 姓名
        ws.cell(r, 3, p.address)              # C 戶籍地址
        ws.cell(r, 4, p.category)             # D 類別（執業所得/薪資）
        ws.cell(r, 5, p.gross)                # E 金額（給付總額）


def _fill_missing_sheet(wb, skipped: list):
    """新增「缺帳戶清單」工作頁：列出缺帳號/代碼者的金額並算總計，避免遺漏。

    skipped: list[(BankPayee, reason)]
    欄位：姓名 / 角色 / 報稅類別 / 應付金額 / 實付金額 / 缺漏原因
    最後一列為總計（應付、實付各加總）。
    """
    from openpyxl.styles import Font, Alignment, Border, Side
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    if SHEET_MISSING in wb.sheetnames:
        del wb[SHEET_MISSING]
    ws = wb.create_sheet(SHEET_MISSING)

    headers = ["姓名", "角色", "報稅類別", "應付金額", "實付金額", "缺漏原因"]
    widths = [12, 14, 12, 12, 12, 22]
    for c, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(1, c, h)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
        cell.border = border
        ws.column_dimensions[chr(64 + c)].width = w

    tot_gross = tot_net = 0
    r = 2
    for p, reason in skipped:
        ws.cell(r, 1, p.name)
        ws.cell(r, 2, p.role)
        ws.cell(r, 3, p.category)
        ws.cell(r, 4, p.gross)
        ws.cell(r, 5, p.amount)
        ws.cell(r, 6, reason)
        for c in range(1, 7):
            ws.cell(r, c).border = border
        tot_gross += p.gross
        tot_net += p.amount
        r += 1

    ws.cell(r, 1, "總計")
    ws.cell(r, 1).font = Font(bold=True)
    ws.cell(r, 4, tot_gross).font = Font(bold=True)
    ws.cell(r, 5, tot_net).font = Font(bold=True)
    for c in range(1, 7):
        ws.cell(r, c).border = border
    return tot_gross, tot_net


def default_template_path() -> str:
    """開發模式 fallback：bank_transfer_writer.py 同層的 word_templates。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "word_templates", "富邦匯款範本.xlsm")


def generate_bank_transfer_file(payees: list, year: int, month: int,
                                output_dir: str, template_path: str = "",
                                progress_cb=None):
    """產生填好的富邦匯款上傳檔（.xlsm，保留巨集）。

    payees: list[BankPayee]
    回傳 (輸出路徑, stats dict)；無有效對象則回傳 (None, stats)。
    stats = {fubon, other, skipped, total_amount, skipped_detail}
    """
    def log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    template_path = template_path or default_template_path()
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"找不到富邦匯款範本：{template_path}")

    payees = _dedupe(payees)

    fubon, other, skipped = [], [], []
    for p in payees:
        if not _digits(p.account_number):
            skipped.append((p, "無帳號"))
        elif _is_fubon(p):
            fubon.append(p)
        elif _digits(p.bank_code):
            other.append(p)
        else:
            skipped.append((p, "無銀行代碼（非富邦無法匯款）"))

    stats = {
        "fubon": len(fubon), "other": len(other), "skipped": len(skipped),
        "total_amount": sum(p.amount for p in fubon + other),
        "skipped_detail": [(p.name, p.role, reason) for p, reason in skipped],
    }

    if not fubon and not other and not skipped:
        log("[富邦匯款檔] 無任何對象，略過產生")
        return None, stats

    wb = openpyxl.load_workbook(template_path, keep_vba=True)
    if SHEET_FUBON in wb.sheetnames:
        _fill_fubon_sheet(wb[SHEET_FUBON], fubon, month)
    if SHEET_OTHER in wb.sheetnames:
        _fill_other_sheet(wb[SHEET_OTHER], other, month)
    # 第三頁報稅清單：列出所有有給付者（含缺帳號者，仍需報稅）
    if SHEET_TAX in wb.sheetnames:
        tax_list = [p for p in payees if p.gross > 0]
        _fill_tax_sheet(wb[SHEET_TAX], tax_list)
        stats["tax_rows"] = len(tax_list)
    # 缺帳戶者：另開工作頁記金額與總計，不遺漏
    if skipped:
        mg, mn = _fill_missing_sheet(wb, skipped)
        stats["missing_total_gross"] = mg
        stats["missing_total_net"] = mn

    prefix = f"{year}年{month:02d}月"
    os.makedirs(output_dir, exist_ok=True)
    base = f"富邦匯款上傳檔-{prefix}"
    out_path = os.path.join(output_dir, base + ".xlsm")
    # 目標檔若正在 Excel 開啟（鎖定）會 PermissionError，改存成 (2)/(3)… 不中斷
    candidates = [out_path] + [
        os.path.join(output_dir, f"{base} ({i}).xlsm") for i in range(2, 21)
    ]
    last_err = None
    for cand in candidates:
        try:
            wb.save(cand)
            out_path = cand
            last_err = None
            break
        except PermissionError as e:
            last_err = e
            continue
    if last_err is not None:
        raise PermissionError(
            f"無法寫入 {base}.xlsm：檔案可能正在 Excel 開啟中，"
            f"請關閉後重試。({last_err})")
    if out_path != os.path.join(output_dir, base + ".xlsm"):
        log(f"※ 原檔被佔用，已另存為：{os.path.basename(out_path)}")

    log(f"[OK] 富邦匯款上傳檔：富邦 {len(fubon)} 筆 / 跨行 {len(other)} 筆"
        f"，匯款總額 {stats['total_amount']:,} 元（實付）")
    if skipped:
        log(f"  缺帳戶 {len(skipped)} 筆已列入「{SHEET_MISSING}」分頁，"
            f"實付小計 {stats.get('missing_total_net', 0):,} 元（待補帳戶）：")
        for name, role, reason in stats["skipped_detail"]:
            log(f"    - {role} {name}：{reason}")

    return out_path, stats
