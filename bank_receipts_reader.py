"""從「已產出的核銷月份資料夾」讀回領據，重建富邦匯款 / 報稅對象。

用途：使用者已用產生器跑出整批核銷文件後，只想單獨產生富邦匯款上傳檔，
不必重跑或重選來源 Excel。走訪所選資料夾找所有 *領據*.docx，抽取：

  - 姓名：領據內文「具領人：」優先，否則檔名 {姓名}_領據
  - 角色：依所在資料夾名稱（處方費→醫師 / 健康管理費→診所行政人員 / 處方處置費→課程老師）
  - 帳戶/個資：戶名 / 銀行及分行 / 分行代號 / 帳號 / 身分證 / 地址（沿用 receipt_reader 抽取）
  - 金額：
      應付（gross）＝內文「新臺幣 X 元整」
      實付（net）  ＝扣稅表「實付」格；無扣稅表（如健管費）則 = 應付
    匯款金額直接採用領據實付，確保與領據一致（不重算）。

報稅類別（第三頁用）：若提供個資檔（人員個資.xlsx）則依其「身分別」判定，
否則依角色推定（醫師→執業所得、課程老師→薪資）。

只讀 .docx（產生器輸出格式），不需 Word/.doc 轉換。
"""

import os
import re

from docx import Document
from docx.oxml.ns import qn

from models import ReceiptInfo
from receipt_reader import (
    _extract_name_from_filename,
    _detect_role_from_filename,
    _extract_receipt_info,
)
from bank_transfer_writer import _payee, _info_get
from tax_rules import category_for

# 資料夾名稱 → 角色（與 receipt_reader.FOLDER_ROLE_MAP 一致）
FOLDER_ROLE_MAP = {
    "處方執行費": "醫師",
    "處方處方費": "醫師",
    "處方費": "醫師",
    "醫師": "醫師",
    "處方處置費": "課程老師",
    "課程老師": "課程老師",
    "老師": "課程老師",
    "健康管理費": "診所行政人員",
    "健管": "診所行政人員",
    "診所行政": "診所行政人員",
    "行政人員": "診所行政人員",
}

_AMOUNT_RE = re.compile(r"新臺幣\s*([\d,，]+)\s*元整")


def _folder_role(folder_path: str) -> str:
    name = os.path.basename(folder_path)
    for kw, r in FOLDER_ROLE_MAP.items():
        if kw in name:
            return r
    return ""


def _to_int(s) -> int:
    digits = "".join(ch for ch in str(s or "") if ch.isdigit())
    return int(digits) if digits else 0


def _extract_amounts(fpath: str):
    """回傳 (gross 應付, net 實付)。net 取扣稅表「實付」格；無扣稅表則 net=gross。"""
    try:
        doc = Document(fpath)
    except Exception:
        return 0, 0
    body = doc.element.body

    concat = "".join(t.text or "" for t in body.iter(qn("w:t")))
    m = _AMOUNT_RE.search(concat)
    gross = _to_int(m.group(1)) if m else 0

    # 扣稅表：3 列，第 0 列含「應付金額」與「實付金額」；第 2 列最後一格 = 實付
    net = gross
    for tbl in body.iter(qn("w:tbl")):
        rows = tbl.findall(qn("w:tr"))
        if len(rows) != 3:
            continue
        head = "".join(t.text or "" for t in rows[0].iter(qn("w:t")))
        if "應付金額" not in head or "實付金額" not in head:
            continue
        cells = rows[2].findall(qn("w:tc"))
        if len(cells) >= 4:
            actual = "".join(t.text or "" for t in cells[3].iter(qn("w:t")))
            v = _to_int(actual)
            if v > 0:
                net = v
        break
    return gross, net


def read_payees_from_output(month_dir: str, people_lookup: dict | None = None,
                            progress_cb=None) -> list:
    """走訪已產出月份資料夾，回傳 list[BankPayee]（金額採領據實付）。

    people_lookup: 選用的 {姓名: ReceiptInfo}（人員個資），用來補身分別→報稅類別。
    """
    def log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    people_lookup = people_lookup or {}
    payees = []
    if not month_dir or not os.path.isdir(month_dir):
        return payees

    count = 0
    for root, _dirs, files in os.walk(month_dir):
        folder_role = _folder_role(root)
        for fname in files:
            base, ext = os.path.splitext(fname)
            if ext.lower() != ".docx":
                continue
            if "領據" not in base or base.startswith("~$"):
                continue

            fpath = os.path.join(root, fname)
            info = _extract_receipt_info(fpath, ".docx") or ReceiptInfo()

            fname_name = _extract_name_from_filename(base)
            name = (info.recipient_name or "").strip() or fname_name
            if not name:
                continue

            role = folder_role or _detect_role_from_filename(base)

            # 個資檔補資料：身分別（領據沒有）＋回填領據缺漏的銀行帳戶/個資
            lk = people_lookup.get(name)
            occupation = _info_get(info, "occupation") or _info_get(lk, "occupation")
            info.occupation = occupation
            for fld in ("id_number", "address", "account_name",
                        "bank_branch", "bank_code", "account_number"):
                if not getattr(info, fld, ""):
                    setattr(info, fld, _info_get(lk, fld))

            gross, net = _extract_amounts(fpath)
            category = category_for(occupation, role)
            p = _payee(name, role, gross, info, net=net, category=category)
            payees.append(p)
            count += 1
            log(f"  ({count}) [{role}] {name}：應付 {gross:,} → 實付 {net:,}")

    log(f"共讀到 {count} 張領據")
    return payees
