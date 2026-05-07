"""從舊領據 Word 檔讀取個人資料，建立姓名→ReceiptInfo 的查找表

支援：
- .docx（python-docx 直讀）
- .doc（win32com 先轉成暫存 .docx，再用 python-docx 讀）

用法：
    lookup = load_receipts_from_dir("D:/115年3月-領據/")
    # lookup == {"王永良": ReceiptInfo(id_number="A123...", address="台北...", ...)}
"""

import os
import tempfile
from docx import Document
from docx.oxml.ns import qn

from models import ReceiptInfo

# 對應表：中文標籤關鍵字 → ReceiptInfo 欄位
LABEL_FIELD_MAP = [
    ("具領",    "recipient_name"),
    ("身分證",  "id_number"),
    ("戶籍",    "address"),
    ("聯絡電話", "phone"),
    ("戶名",    "account_name"),
    ("銀行及分行", "bank_branch"),
    ("銀行代碼", "bank_code"),
    ("帳號",    "account_number"),
]


def load_receipts_from_dir(dir_path: str,
                           progress_cb=None) -> dict[str, ReceiptInfo]:
    """掃描資料夾，讀取所有 *核銷領據.doc/.docx，
    回傳 {姓名: ReceiptInfo}（金額欄位設為 0，由主程式填入）

    progress_cb(msg: str)：每讀完一筆呼叫，可用來更新 UI 進度
    優化：同名只讀一份（優先 .docx），.doc 批次轉換避免重複開關 Word
    """
    def log(msg):
        if progress_cb:
            progress_cb(msg)
    if not dir_path or not os.path.isdir(dir_path):
        return {}

    # 資料夾名稱 → 角色對應（優先於檔名判斷）
    FOLDER_ROLE_MAP = {
        # 醫師類
        "醫師": "醫師",
        "處方執行費": "醫師",
        "處方處方費": "醫師",
        "處方費": "醫師",
        # 課程老師類
        "課程老師": "課程老師",
        "老師": "課程老師",
        "處方處置費": "課程老師",
        # 診所行政人員類
        "健康管理費": "診所行政人員",
        "診所行政": "診所行政人員",
        "行政人員": "診所行政人員",
        "健管": "診所行政人員",
    }

    def _folder_role(folder_path: str) -> str:
        """從資料夾名稱判斷角色，找不到就回傳空字串（靠檔名判斷）"""
        folder_name = os.path.basename(folder_path)
        for kw, r in FOLDER_ROLE_MAP.items():
            if kw in folder_name:
                return r
        return ""

    # 第一步：遞迴掃描所有檔案，每人只保留一個最佳檔案（.docx 優先）
    best: dict[str, tuple[str, str, str]] = {}  # name → (fpath, ext, role)
    for root, _dirs, files in os.walk(dir_path):
        folder_forced_role = _folder_role(root)  # 資料夾強制角色（空=靠檔名）
        for fname in files:
            base, ext = os.path.splitext(fname)
            ext_lower = ext.lower()
            if ext_lower not in (".doc", ".docx"):
                continue
            if "領據" not in base and "receipt" not in base.lower():
                continue
            name = _extract_name_from_filename(base)
            if not name:
                continue
            # 角色：資料夾名稱優先，否則靠檔名判斷
            role = folder_forced_role or _detect_role_from_filename(base)
            fpath = os.path.join(root, fname)
            # 同名時：資料夾強制角色 > 醫師 > 其他；再比 .docx 優先
            if name not in best:
                best[name] = (fpath, ext_lower, role)
            else:
                prev_role = best[name][2]
                # 有資料夾強制角色的優先
                if folder_forced_role and not _folder_role(os.path.dirname(best[name][0])):
                    best[name] = (fpath, ext_lower, role)
                elif role == "醫師" and prev_role != "醫師" and not folder_forced_role:
                    best[name] = (fpath, ext_lower, role)
                elif ext_lower == ".docx" and best[name][1] != ".docx":
                    best[name] = (fpath, ext_lower, role)

    if not best:
        return {}

    total = len(best)
    log(f"找到 {total} 位人員，開始讀取...")

    # 第二步：.doc 批次轉換（只開關 Word 一次）
    doc_items = [(n, p) for n, (p, e, r) in best.items() if e == ".doc"]
    docx_cache: dict[str, str] = {}
    if doc_items:
        log(f"轉換 {len(doc_items)} 個 .doc 檔（請稍候）...")
        docx_cache = _batch_doc_to_docx([p for _, p in doc_items])

    # 第三步：逐一讀取
    lookup: dict[str, ReceiptInfo] = {}
    for i, (name, (fpath, ext_lower, role)) in enumerate(best.items(), 1):
        lookup[name] = ReceiptInfo(recipient_name=name, role=role)
        try:
            read_path = docx_cache.get(fpath, fpath) if ext_lower == ".doc" else fpath
            read_ext  = ".docx" if ext_lower == ".doc" else ext_lower
            info = _extract_receipt_info(read_path, read_ext)
            if info:
                existing = lookup[name]
                has_data = False
                for field in ("id_number", "address", "phone",
                              "account_name", "bank_branch",
                              "bank_code", "account_number"):
                    if not getattr(existing, field) and getattr(info, field):
                        setattr(existing, field, getattr(info, field))
                        has_data = True

                # 診所行政人員：若戶名是有效人名，以戶名作為 Excel 姓名鍵值
                # 診所名稱保留在 recipient_name（具領人欄位，印在領據上）
                key_name = name
                if role == "診所行政人員":
                    an = (existing.account_name or "").strip()
                    if an and _is_valid_name(an) and an != name:
                        # 把這筆移到以人名為 key
                        lookup.pop(name, None)
                        existing.recipient_name = name  # 診所名保留給具領人
                        existing.clinic_name = name     # 同時存入所屬診所欄
                        lookup[an] = existing
                        key_name = an
                    else:
                        # 找不到人名，以診所名為 key，診所名也存進 clinic_name
                        existing.clinic_name = name

                status = "[OK]" if has_data else "[--]"
                log(f"  ({i}/{total}) {status} [{role}] {key_name}")
            else:
                log(f"  ({i}/{total}) [--] [{role}] {name} (僅記錄名字)")
        except Exception:
            log(f"  ({i}/{total}) [NG] [{role}] {name} (讀取失敗)")

    # 清理暫存 .docx
    for tmp in docx_cache.values():
        try:
            os.remove(tmp)
        except OSError:
            pass

    return lookup


def _extract_name_from_filename(base: str) -> str:
    """從檔名解析人名，支援以下格式：

    1. 個人核銷領據(不扣稅)-11503月-何叔芳-處方費-$1,500  → 何叔芳
    2. 個人核銷領據(不扣稅)-11503月-情緒-呂惠萍$4,800     → 呂惠萍
    3. 個人核銷領據(不扣稅)-11503月-健康管理費-王永良診所  → 跳過（診所）
    4. 領據-扣稅-11503月-李政璋-處方費$38400              → 李政璋
    5. 何叔芳_領據                                        → 何叔芳（執行人員格式）
    6. 何叔芳_處方費領據 / 何叔芳_處方執行費領據            → 何叔芳（醫師格式）
    """
    import re
    # 去掉括號內容
    base = re.sub(r"[（(][^）)]*[）)]", "", base).strip()

    # 格式 5/6：{姓名}_領據 / {姓名}_處方費領據 / {姓名}_處方執行費領據
    # 下底線分隔，第一段就是姓名
    if "_" in base and "領據" in base:
        candidate = _strip_amount(base.split("_")[0]).strip()
        if _is_valid_name(candidate):
            return candidate

    parts = [p.strip() for p in base.split("-")]

    # 格式 1/2/3：個人核銷領據-YYYYMM月-[分類or姓名]-...
    if parts and "核銷領據" in parts[0]:
        if len(parts) >= 3:
            # 健康管理費格式：
            #   A) ...-健康管理費-{人名}$金額           → 直接回傳人名
            #   B) ...-健康管理費-{診所名}-{人名}$金額  → 人名在 parts[4]
            #   C) ...-健康管理費-{診所名}$金額         → 靠 Word 戶名換人名
            if "健康管理費" in parts[2] and len(parts) >= 4:
                p3 = _strip_amount(parts[3]).strip()
                # 格式 B：parts[4] 是有效人名 → 優先使用
                if len(parts) >= 5:
                    p4 = _strip_amount(parts[4]).strip()
                    if p4 and _is_valid_name(p4):
                        return p4
                # 格式 A or C：parts[3] 直接回傳
                if p3:
                    return p3
            # parts[2] 可能是姓名或分類詞（情緒/運動/社會/營養）
            candidate = _strip_amount(parts[2])
            if _is_valid_name(candidate):
                return candidate
            # 分類詞→ parts[3] 才是姓名
            if len(parts) >= 4:
                candidate = _strip_amount(parts[3])
                if _is_valid_name(candidate):
                    return candidate

    # 格式 4：領據-扣稅-YYYYMM月-姓名-費用
    if parts and parts[0] in ("領據", "领据"):
        if len(parts) >= 4:
            candidate = _strip_amount(parts[3])
            if _is_valid_name(candidate):
                return candidate

    return ""  # 無法解析就跳過


def _detect_role_from_filename(base: str) -> str:
    """從檔名判斷角色：
    - 醫師：處方費、處方執行費
    - 課程老師：處方處置費
    - 診所行政人員：健康管理費
    """
    # 處方費 / 處方執行費 → 醫師
    if "處方執行費" in base:
        return "醫師"
    if "處方費" in base and "處置" not in base:
        return "醫師"
    # 扣稅領據（金額大）→ 醫師
    if "扣稅" in base:
        return "醫師"
    # 處方處置費 → 課程老師
    if "處方處置費" in base:
        return "課程老師"
    # 健康管理費 → 診所行政人員
    if "健康管理費" in base:
        return "診所行政人員"
    # {姓名}_領據（執行人員格式）→ 課程老師
    if "_領據" in base and "處方" not in base:
        return "課程老師"
    # 個人核銷領據 預設課程老師
    return "課程老師"


def _strip_amount(s: str) -> str:
    """去除字串尾端的金額（$1,500 / $7000 等）"""
    import re
    return re.sub(r"[\s　]*[$＄][\d,，]+.*$", "", s).strip()


def _is_valid_name(name: str) -> bool:
    """判斷字串是否像人名（2–4 字中文，無數字/診所/機構/分類關鍵字）"""
    import re
    if not name or len(name) < 2 or len(name) > 4:
        return False
    # 排除明顯非人名的關鍵字
    INVALID_KW = (
        "診所", "醫院", "醫學", "中心", "機制", "臨時", "個人",
        "管理費", "template", "範本", "測試", "sample", "更新",
        # 費用分類詞
        "情緒", "社會", "運動", "營養", "健康", "處方", "執行",
    )
    for kw in INVALID_KW:
        if kw in name:
            return False
    # 不含數字、金額符號
    if re.search(r"[\d$＄_]", name):
        return False
    # 若含英文大寫字母（2個以上），通常是機構縮寫（如 ENT）
    if len(re.findall(r"[A-Z]", name)) >= 2:
        return False
    return True


def _extract_receipt_info(fpath: str, ext: str) -> ReceiptInfo | None:
    """讀取一份領據檔，抽取個人資料"""
    if ext == ".docx":
        doc = Document(fpath)
    elif ext == ".doc":
        doc = _doc_to_docx_and_open(fpath)
    else:
        return None

    if doc is None:
        return None

    info = ReceiptInfo()
    _fill_from_tables(doc, info)
    _fill_from_paragraphs(doc, info)
    return info


def _batch_doc_to_docx(doc_paths: list[str]) -> dict[str, str]:
    """批次將多個 .doc 轉成暫存 .docx，只開關 Word 一次。
    回傳 {原始路徑: 暫存 docx 路徑}
    """
    result: dict[str, str] = {}
    if not doc_paths:
        return result
    try:
        import win32com.client
    except ImportError:
        return result

    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        for i, doc_path in enumerate(doc_paths):
            tmp_path = os.path.join(
                tempfile.gettempdir(),
                f"receipt_batch_{os.getpid()}_{i}.docx"
            )
            try:
                wdoc = word.Documents.Open(os.path.abspath(doc_path))
                wdoc.SaveAs(os.path.abspath(tmp_path), FileFormat=12)
                wdoc.Close()
                result[doc_path] = tmp_path
            except Exception:
                pass
    finally:
        word.Quit()
    return result


def _doc_to_docx_and_open(doc_path: str):
    """用 win32com 將 .doc 轉成暫存 .docx，再用 python-docx 開啟"""
    try:
        import win32com.client
    except ImportError:
        print("  [WARN] win32com 未安裝，無法讀取 .doc 檔")
        return None

    tmp_path = os.path.join(
        tempfile.gettempdir(),
        f"receipt_tmp_{os.getpid()}.docx"
    )
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        wdoc = word.Documents.Open(os.path.abspath(doc_path))
        wdoc.SaveAs(os.path.abspath(tmp_path), FileFormat=12)  # 12 = docx
        wdoc.Close()
    except Exception as e:
        print(f"  [WARN] win32com 轉換失敗: {e}")
        return None
    finally:
        word.Quit()

    try:
        return Document(tmp_path)
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _fill_from_tables(doc, info: ReceiptInfo):
    """從表格的每一行掃描 標籤|值 結構"""
    for table in doc.tables:
        for row in table.rows:
            cells = row.cells
            if len(cells) < 2:
                continue
            label_text = _cell_text(cells[0])
            value_text = _cell_text(cells[1])
            _try_assign(info, label_text, value_text)


def _fill_from_paragraphs(doc, info: ReceiptInfo):
    """從所有文字段落掃描「標籤：值」格式
    涵蓋：body 段落、表格 cell、文字框（w:txbxContent）
    """
    # 收集所有 w:p 元素（包含文字框內）
    all_paras = list(doc.element.body.iter(qn("w:p")))

    for p_elem in all_paras:
        text = "".join(t.text or "" for t in p_elem.iter(qn("w:t"))).strip()
        for sep in ("：", ":"):
            if sep in text:
                parts = text.split(sep, 1)
                if len(parts) == 2:
                    _try_assign(info, parts[0].strip(), parts[1].strip())
                break


def _try_assign(info: ReceiptInfo, label: str, value: str):
    """根據 label 文字判斷要填哪個欄位"""
    value = value.strip()
    if not value:
        return
    # 排除明顯不是真實資料的值（空白格、佔位符）
    SKIP_VALUES = ("個人", "姓名", "請填寫", "（請填）", "　", " ")
    if value in SKIP_VALUES:
        return
    for keyword, field in LABEL_FIELD_MAP:
        if keyword in label:
            # 具領人名字要通過人名驗證
            if field == "recipient_name" and not _is_valid_name(value):
                return
            # 只填入尚未設定的欄位（避免重複覆蓋）
            if not getattr(info, field):
                setattr(info, field, value)
            return


def _cell_text(cell) -> str:
    """取得 cell 的完整文字"""
    return "".join(
        t.text for t in cell._tc.iter(qn("w:t"))
    ).strip()
