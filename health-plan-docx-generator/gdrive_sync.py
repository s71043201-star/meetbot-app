"""Google Drive 共用檔案下載助手。

支援 Google Sheet（原生）與 uploaded .xlsx，使用「擁有連結者可檢視」
分享設定，無需 OAuth。下載失敗時不會覆蓋既有本機檔案（先寫 .tmp 再 rename）。
"""
from __future__ import annotations

import os
import re
import urllib.request
from typing import Optional


_FILE_ID_PATTERNS = [
    r"/d/([a-zA-Z0-9_-]+)",
    r"[?&]id=([a-zA-Z0-9_-]+)",
]


def parse_file_id(url_or_id: str) -> Optional[str]:
    """從 Google Drive / Sheets 連結抽出 file ID；若已是純 ID 則原樣回傳。"""
    if not url_or_id:
        return None
    s = url_or_id.strip()
    if "/" not in s and "?" not in s:
        return s
    for pat in _FILE_ID_PATTERNS:
        m = re.search(pat, s)
        if m:
            return m.group(1)
    return None


def _try_download(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (HealthPlanDocsGenerator)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ct = (resp.headers.get("Content-Type") or "").lower()
        data = resp.read()
    # 過濾 Drive 大檔回傳的 virus-scan HTML 確認頁
    if "text/html" in ct and not data.startswith(b"PK"):
        raise RuntimeError("Google Drive 回傳 HTML 頁（可能需要 virus-scan token 或檔案過大）")
    if not data:
        raise RuntimeError("下載結果為空")
    return data


def download_xlsx(url_or_id: str, dest_path: str, timeout: int = 30) -> str:
    """下載 Google Drive 上的 .xlsx 到 dest_path。
    成功回傳 dest_path；失敗 raise。下載中本機既有檔案不會被毀。
    """
    file_id = parse_file_id(url_or_id)
    if not file_id:
        raise ValueError(f"無法解析 Google Drive ID：{url_or_id}")

    candidates = [
        f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx",
        f"https://drive.google.com/uc?export=download&id={file_id}",
    ]

    last_err: Optional[Exception] = None
    data: Optional[bytes] = None
    for url in candidates:
        try:
            data = _try_download(url, timeout)
            break
        except Exception as e:
            last_err = e
            continue

    if data is None:
        raise RuntimeError(f"下載失敗：{last_err}")

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    tmp = dest_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest_path)
    return dest_path
