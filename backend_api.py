"""直接向健康處方管理系統後端抓核銷資料，取代手動匯出兩個 Excel。

對應你原本的操作（核銷管理頁）：

    開立資料 = 核銷管理 → 處方費     → 日期類型「開立日期」→ 選區間 → 查詢
             = fee_key=prescription_fee & date_field=created_at
    執行資料 = 核銷管理 → 處方處置費 → 日期類型「執行日期」→ 選區間 → 查詢
             = fee_key=treatment_fee    & date_field=execution_date

API 回傳的欄位是現行 Excel 22 欄的超集，所以這裡把它轉回同樣的 row tuple
順序後，reader.py 的欄位索引完全不用改。

帳密只從 secrets.json 讀（RX_ACCOUNT / RX_PASSWORD），不寫在程式裡；
secrets.json 已列入 .gitignore，不會進 git。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from config import (
    RX_BACKEND_URL,
    RX_ORIGIN,
    RX_ACCOUNT,
    RX_PASSWORD,
)

# 核銷管理頁的「費用項目」頁籤
FEE_KEY_PRESCRIPTION = "prescription_fee"   # 處方費
FEE_KEY_EXECUTION = "execution_fee"         # 處方執行費
FEE_KEY_TREATMENT = "treatment_fee"         # 處方處置費

# 核銷管理頁的「日期類型」
DATE_FIELD_ISSUE = "created_at"             # 開立日期
DATE_FIELD_EXEC = "execution_date"          # 執行日期

PAGE_SIZE = 200          # 後端允許的較大頁；抓 8000 筆約 40 次請求
REQUEST_TIMEOUT = 60


class RxApiError(RuntimeError):
    """後端 API 呼叫失敗（含帳密未設定、登入失敗、查詢失敗）"""


# ---------------------------------------------------------------- 低階 HTTP
def _request(method: str, url: str, *, token: str = "", body: Optional[dict] = None) -> dict:
    data = None
    headers = {"Origin": RX_ORIGIN, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", "")
        except Exception:
            pass
        raise RxApiError(f"HTTP {e.code} {url.split('?')[0]} {detail}".strip()) from e
    except urllib.error.URLError as e:
        raise RxApiError(f"連不到後端（{e.reason}）") from e


# ---------------------------------------------------------------- token
class _Session:
    """管理 access / refresh token。token 只留在記憶體，不落地。"""

    def __init__(self, account: str, password: str):
        if not account or not password:
            raise RxApiError(
                "尚未設定後端帳密。請在 secrets.json 填入 RX_ACCOUNT 與 RX_PASSWORD"
                "（格式見 secrets.json.example）。")
        self._account = account
        self._password = password
        self._token = ""
        self._exp = 0.0
        self._refresh = ""
        self._refresh_exp = 0.0

    @staticmethod
    def _exp_of(jwt: str) -> float:
        """讀 JWT 的 exp（失敗就當作 5 分鐘後過期，讓它自然重登）"""
        try:
            payload = jwt.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            import base64
            return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
        except Exception:
            return time.time() + 300

    def _apply(self, r: dict) -> None:
        self._token = r.get("access_token") or ""
        if not self._token:
            raise RxApiError("登入回應沒有 access_token")
        self._exp = self._exp_of(self._token)
        if r.get("refresh_token"):
            self._refresh = r["refresh_token"]
            self._refresh_exp = self._exp_of(self._refresh)

    def token(self) -> str:
        now = time.time()
        if self._token and self._exp > now + 30:
            return self._token
        # 先試 refresh，失敗再用帳密登入
        if self._refresh and self._refresh_exp > now + 60:
            try:
                self._apply(_request(
                    "POST", f"{RX_BACKEND_URL}/api/v1/auth/refresh",
                    body={"refresh_token": self._refresh}))
                return self._token
            except RxApiError:
                pass
        self._apply(_request(
            "POST", f"{RX_BACKEND_URL}/api/v1/auth/login",
            body={"account": self._account, "password": self._password}))
        return self._token


# ---------------------------------------------------------------- 欄位轉換
def _flag(v):
    """勾選類欄位 → 與 Excel 一致的 'V'（未勾為 None）。

    後端可能回 True / 'V' / '是' / 1，Excel 匯出一律是 'V'；數字（金額）原樣保留。
    """
    if v is None or v is False or v == "":
        return None
    if v is True:
        return "V"
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if not s:
        return None
    if s.lower() in ("false", "0", "n", "no"):
        return None
    if s.lower() in ("true", "1", "y", "yes", "是", "已執行", "✓", "v"):
        return "V"
    return s


def _date_iso(v):
    """日期 → 'YYYY-MM-DD'（保留連字號）。

    生日欄在 Excel 匯出裡是連字號（1985-06-23），跟執行日期的斜線格式
    （2026/08/20）不同 —— 民眾明細會直接印這個值，格式要跟現況一致。
    """
    if not v:
        return None
    s = str(v).strip().replace("T", " ").split(" ")[0]
    return s or None


def _date(v, with_time: bool = False):
    """日期 → Excel 風格 'YYYY/MM/DD'（開立日期時間保留時分秒）"""
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("T", " ")
    head, _, tail = s.partition(" ")
    head = head.replace("-", "/")
    if with_time and tail:
        return f"{head} {tail.split('.')[0]}"
    return head


def record_to_row(rec: dict) -> tuple:
    """API record → 與 Excel「處方紀錄」同順序的 22 欄 row。

    欄位對照已逐欄核對過（department = 執行單位、participated_course = 執行課程）。
    """
    return (
        rec.get("prescription_no"),                 # 0  流水號
        rec.get("patient_name"),                    # 1  姓名
        rec.get("gender"),                          # 2  性別
        _date_iso(rec.get("birth_date")),           # 3  生日（連字號，同 Excel）
        rec.get("id_number"),                       # 4  身分證字號
        rec.get("phone"),                           # 5  手機
        rec.get("prescription_type"),               # 6  處方類型
        rec.get("clinic_name"),                     # 7  開立診所
        rec.get("physician_name"),                  # 8  開立醫師
        _flag(rec.get("course_selected_flag")),     # 9  是否選課
        rec.get("booking_course_name"),             # 10 選課名稱
        rec.get("booking_slot"),                    # 11 選課時段
        rec.get("department"),                      # 12 執行單位
        rec.get("executor_name"),                   # 13 執行人員
        _flag(rec.get("executed_flag")),            # 14 執行處方
        rec.get("participated_course"),             # 15 執行課程
        _date(rec.get("execution_date")),           # 16 執行日期
        _flag(rec.get("prescription_fee")),         # 17 處方費
        _flag(rec.get("execution_fee")),            # 18 處方執行費
        _flag(rec.get("treatment_fee")),            # 19 處方處置費
        _flag(rec.get("reimbursed_flag")),          # 20 已核銷
        _date(rec.get("issue_date"), with_time=True),  # 21 開立日期時間
    )


# ---------------------------------------------------------------- 查詢
def fetch_rows(start_date: str,
               end_date: str,
               fee_key: str,
               date_field: str,
               *,
               session: Optional[_Session] = None,
               progress: Optional[Callable[[str], None]] = None) -> list:
    """抓一種「費用項目 × 日期類型」的全部紀錄，回傳 Excel 格式的 row 列表。

    start_date / end_date 為 'YYYY-MM-DD'（西元）。會自動翻頁抓完。
    """
    sess = session or _Session(RX_ACCOUNT, RX_PASSWORD)
    rows: list = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        qs = urllib.parse.urlencode({
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "page_size": PAGE_SIZE,
            "fee_key": fee_key,
            "fee_status": "all",
            "date_field": date_field,
            "sort_by": date_field,
            "sort_order": "asc",
        })
        data = _request(
            "GET", f"{RX_BACKEND_URL}/api/v1/prescription/records/report?{qs}",
            token=sess.token())
        for rec in (data.get("records") or []):
            rows.append(record_to_row(rec))
        pg = data.get("pagination") or {}
        total_pages = int(pg.get("total_pages") or 1)
        if progress:
            progress(f"{fee_key}：第 {page}/{total_pages} 頁，累計 {len(rows)} 筆")
        page += 1
    return rows


def month_range(year_ad: int, month: int) -> tuple:
    """西元年月 → ('YYYY-MM-01', 'YYYY-MM-<該月最後一天>')"""
    import calendar
    last = calendar.monthrange(year_ad, month)[1]
    return f"{year_ad:04d}-{month:02d}-01", f"{year_ad:04d}-{month:02d}-{last:02d}"


def fetch_month(year_ad: int,
                month: int,
                *,
                progress: Optional[Callable[[str], None]] = None) -> tuple:
    """抓某月的（開立 rows, 執行 rows），對應原本要匯出的兩個 Excel。"""
    start, end = month_range(year_ad, month)
    sess = _Session(RX_ACCOUNT, RX_PASSWORD)
    if progress:
        progress(f"查詢區間 {start} ～ {end}")
    issuance = fetch_rows(start, end, FEE_KEY_PRESCRIPTION, DATE_FIELD_ISSUE,
                          session=sess, progress=progress)
    execution = fetch_rows(start, end, FEE_KEY_TREATMENT, DATE_FIELD_EXEC,
                           session=sess, progress=progress)
    if progress:
        progress(f"完成：開立 {len(issuance)} 筆、執行 {len(execution)} 筆")
    return issuance, execution


def check_connection() -> str:
    """測試帳密與連線，回傳一行結果訊息（供 UI 顯示）。"""
    sess = _Session(RX_ACCOUNT, RX_PASSWORD)
    sess.token()
    return f"連線成功：{RX_BACKEND_URL}"
