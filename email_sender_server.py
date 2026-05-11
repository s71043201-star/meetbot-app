"""Gmail 寄送器 — 純瀏覽器版（取代 pywebview）

跑法：
    python email_sender_server.py
或：
    python 啟動寄送器.py     ← 第一次會自動 pip install

開一個本機 HTTP server (port 5174)，並用預設瀏覽器打開頁面。
所有原本 pywebview 的 JsApi 都包成 POST /api/<method>，事件透過 SSE
/api/events 推回前端。

放置位置：與 email_sender.py / people_db.py / Gmail 寄送器.html 同層。
"""

from __future__ import annotations

import http.server
import json
import os
import queue
import socketserver
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from datetime import date

import copy
import random
import re

from email_sender import (
    EmailJob,
    RECEIPT_TEMPLATE_FILENAME,
    SmtpAuthError,
    _describe_attachment,
    build_body,
    build_email_jobs,
    is_valid_email_format,
    send_via_gmail_smtp,
)
from people_db import load_people_db, load_reviewers


def _job_main_category(j: EmailJob) -> str:
    """回傳 job 主要費用類別(取第一個非範本 PDF 的 category)。

    用來把 jobs 分桶,讓「各種費用各一」的預審樣本盡量涵蓋所有類別。
    都查不到就回空字串。
    """
    for p in j.attachments:
        if os.path.basename(p) == RECEIPT_TEMPLATE_FILENAME:
            continue
        cat = _describe_attachment(p)
        if cat:
            return cat
    return ""


def _pick_samples_for_reviewers(
    jobs: list[EmailJob], n: int
) -> list[EmailJob]:
    """從 pending+selected jobs 中為 n 位 reviewer 各挑一筆樣本。

    規則:
      1. 按費用類別分桶,先從每個桶隨機抽一筆 → 「各種費用各一」
      2. 桶不夠時(reviewer 數 > 類別數),再從剩下所有未抽到的 jobs 隨機補
      3. 樣本還是不夠(整體待寄人員 < reviewer 數)時,允許重複抽
    """
    pool = [j for j in jobs if j.status == "pending" and j.selected]
    if not pool or n <= 0:
        return []

    by_cat: dict[str, list[EmailJob]] = {}
    for j in pool:
        cat = _job_main_category(j) or "_其他_"
        by_cat.setdefault(cat, []).append(j)

    cats = list(by_cat.keys())
    random.shuffle(cats)

    samples: list[EmailJob] = []
    used: set[int] = set()
    for c in cats:
        if len(samples) >= n:
            break
        chosen = random.choice(by_cat[c])
        samples.append(chosen)
        used.add(id(chosen))

    if len(samples) < n:
        remaining = [j for j in pool if id(j) not in used]
        random.shuffle(remaining)
        while len(samples) < n and remaining:
            samples.append(remaining.pop())

    while len(samples) < n:
        samples.append(random.choice(pool))

    return samples


if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    BASE_DIR = sys._MEIPASS  # type: ignore[attr-defined]
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = APP_DIR

# HTML 直接放在 APP_DIR 同層
WEB_DIR = APP_DIR
PORT = 5174

SEND_INTERVAL_SECONDS = 1.5

PEOPLE_DB_CANDIDATES = [
    "人員個資+分行_已填代號.xlsx",
    "人員個資+分行.xlsx",
    "人員個資.xlsx",
]


# ─── 事件 broker：SSE ───
_event_q: queue.Queue = queue.Queue()


def emit(event, payload):
    _event_q.put({"event": event, "data": payload})


# ─── 對話框：必須在主執行緒處理 Tk，用 queue 傳遞請求 ───
_dlg_request_q: queue.Queue = queue.Queue()
_dlg_result_q: queue.Queue = queue.Queue()
_dlg_serial_lock = threading.Lock()


def _pick_file(xlsx_only: bool = False) -> str:
    with _dlg_serial_lock:
        while not _dlg_result_q.empty():
            try:
                _dlg_result_q.get_nowait()
            except queue.Empty:
                break
        _dlg_request_q.put({"kind": "file", "xlsx_only": xlsx_only})
        return _dlg_result_q.get()


def _pick_folder() -> str:
    with _dlg_serial_lock:
        while not _dlg_result_q.empty():
            try:
                _dlg_result_q.get_nowait()
            except queue.Empty:
                break
        _dlg_request_q.put({"kind": "folder"})
        return _dlg_result_q.get()


def _dialog_pump(root):
    """主 thread 上跑：每 50ms 檢查 queue，有請求就開對話框。"""
    try:
        while True:
            try:
                req = _dlg_request_q.get_nowait()
            except queue.Empty:
                break
            try:
                from tkinter import filedialog
                # 強制把 root 拉到最前面，避免對話框藏到瀏覽器背後
                root.deiconify()
                root.lift()
                root.focus_force()
                root.attributes("-topmost", True)
                root.update()
                if req["kind"] == "file":
                    types = (
                        [("Excel", "*.xlsx"), ("All", "*.*")]
                        if req.get("xlsx_only")
                        else [("All", "*.*")]
                    )
                    p = filedialog.askopenfilename(parent=root, filetypes=types)
                    _dlg_result_q.put(p or "")
                elif req["kind"] == "folder":
                    p = filedialog.askdirectory(parent=root)
                    _dlg_result_q.put(p or "")
                else:
                    _dlg_result_q.put("")
                root.withdraw()
            except Exception:
                traceback.print_exc()
                _dlg_result_q.put("")
    finally:
        root.after(50, lambda: _dialog_pump(root))


def _log(line: str):
    emit("log-line", line)


def _progress(done: int, total: int, status: str = ""):
    pct = (done / total) if total else 0
    emit("progress-update", {
        "done": done, "total": total, "pct": pct, "status": status,
    })


# ─── App Password 清洗 ───
_INVISIBLE_ORDS = {0x200B, 0x200C, 0x200D, 0xFEFF, 0x3000, 0x00A0}


def _normalize_app_password(raw: str) -> str:
    cleaned = []
    for c in raw or "":
        if c.isspace():
            continue
        if ord(c) in _INVISIBLE_ORDS:
            continue
        if 32 < ord(c) < 127:
            cleaned.append(c)
    return "".join(cleaned)


def _job_to_dict(j: EmailJob, idx: int) -> dict:
    return {
        "idx": idx,
        "person_name": j.person_name,
        "role": j.role or "",
        "clinic_name": j.clinic_name or "",
        "to_email": j.to_email or "",
        "zone": j.zone or "",
        "subject": j.subject or "",
        "status": j.status,
        "error": j.error or "",
        "attachments_count": len(j.attachments),
        "attachments": [os.path.basename(p) for p in j.attachments],
        "total_bytes": j.total_attachment_bytes,
        "selected": j.selected,
    }


class EmailSenderApi:
    def __init__(self):
        self._jobs: list[EmailJob] = []
        self._sender_email: str = ""
        self._send_thread: threading.Thread | None = None
        self._cancel_flag = threading.Event()

    def pickFolder(self):
        return _pick_folder() or None

    def pickFile(self, accept: str = ""):
        return _pick_file(xlsx_only="xlsx" in (accept or "")) or None

    def fileExists(self, path: str) -> bool:
        return bool(path) and os.path.exists(path)

    def getInitialState(self):
        today = date.today()
        roc_year = today.year - 1911
        if today.month == 1:
            prev_year, prev_month = roc_year - 1, 12
        else:
            prev_year, prev_month = roc_year, today.month - 1

        people_db = ""
        for cand in PEOPLE_DB_CANDIDATES:
            p = os.path.join(APP_DIR, cand)
            if os.path.exists(p):
                people_db = p
                break
        if not people_db:
            people_db = os.path.join(APP_DIR, "人員個資.xlsx")

        return {
            "year": prev_year,
            "month": prev_month,
            "output": os.path.join(APP_DIR, "核銷文件"),
            "peopleDb": people_db,
            "senderEmail": "tpma.healthtw@gmail.com",
            "templateDriveLink": "",
        }

    def listReviewers(self, people_db_path: str) -> list[dict]:
        """讀個資 Excel 的「計畫人員個資」工作頁,提供 reviewer 下拉選單來源。"""
        path = (people_db_path or "").strip()
        if not path:
            # 沒指定就回傳 getInitialState 推得的路徑
            for cand in PEOPLE_DB_CANDIDATES:
                p = os.path.join(APP_DIR, cand)
                if os.path.exists(p):
                    path = p
                    break
        return load_reviewers(path)

    def listZones(self, output: str, year, month) -> list[str]:
        try:
            year = int(year); month = int(month)
        except (ValueError, TypeError):
            return []
        month_dir = os.path.join((output or "").strip(),
                                  f"{year}年{month:02d}月")
        if not os.path.isdir(month_dir):
            return []
        try:
            return sorted(
                d for d in os.listdir(month_dir)
                if os.path.isdir(os.path.join(month_dir, d))
                and not d.startswith(".")
            )
        except OSError:
            return []

    def previewBody(self, s: dict) -> str:
        try:
            year = int(s.get("year", 115))
            month = int(s.get("month", 4))
        except (ValueError, TypeError):
            year, month = 115, 4

        template_link = (s.get("templateDriveLink") or "").strip()
        extra = (s.get("extraMessage") or "").strip()
        deadline = (s.get("deadline") or "").strip()

        sample = ["{姓名}_明細領據.pdf"]
        if not template_link:
            sample.append("領據填寫範例.pdf")

        return build_body(
            person_name="{姓名}", role="{職稱}", clinic_name="{診所}",
            roc_year=year, roc_month=month,
            attachments=sample,
            template_drive_link=template_link,
            extra_message=extra,
            deadline=deadline,
        )

    def scanJobs(self, s: dict) -> dict:
        try:
            year = int(s["year"]); month = int(s["month"])
        except (KeyError, ValueError, TypeError):
            raise RuntimeError("年月必須是數字")

        output = (s.get("output") or "").strip()
        if not output:
            raise RuntimeError("請先選擇核銷文件根資料夾")

        prefix = f"{year}年{month:02d}月"
        month_dir = os.path.join(output, prefix)
        if not os.path.isdir(month_dir):
            raise RuntimeError(f"找不到月份資料夾：{month_dir}")

        zones = s.get("selectedZones") or []
        all_zones = self.listZones(output, year, month)
        if all_zones and not zones:
            raise RuntimeError("請至少勾選一個區別")
        zones_arg = None if (set(zones) == set(all_zones)) else zones or None

        receipt_lookup = {}
        db_path = (s.get("peopleDb") or "").strip()
        if db_path and os.path.exists(db_path):
            receipt_lookup = load_people_db(db_path)
            _log(f"已讀取個資 {len(receipt_lookup)} 筆")

        template_link = (s.get("templateDriveLink") or "").strip()
        extra_message = (s.get("extraMessage") or "").strip()
        deadline = (s.get("deadline") or "").strip()

        _log(f"掃描 {month_dir}"
             f"{('（區別：' + '、'.join(zones) + '）') if zones_arg else '（全部區別）'}")

        jobs = build_email_jobs(
            month_dir, receipt_lookup, year, month,
            template_drive_link=template_link,
            extra_message=extra_message,
            allowed_zones=zones_arg,
            deadline=deadline,
        )

        subj_tpl = (s.get("subjectTemplate") or "").strip()
        pinned = (s.get("pinnedMessage") or "").strip()
        for j in jobs:
            if subj_tpl:
                j.subject = (
                    subj_tpl
                    .replace("{年}", str(year))
                    .replace("{月}", f"{month:02d}")
                    .replace("{姓名}", j.person_name or "")
                    .replace("{職稱}", j.role or "")
                    .replace("{診所}", j.clinic_name or "")
                )
            if pinned:
                j.body = f"📌 {pinned}\n\n" + j.body

        self._jobs = jobs
        self._sender_email = (s.get("senderEmail") or "").strip()

        sendable = sum(1 for j in jobs if j.status == "pending")
        _log(f"找到 {len(jobs)} 位人員，可寄送 {sendable} 位")

        return {
            "jobs": [_job_to_dict(j, i) for i, j in enumerate(jobs)],
            "sendable": sendable,
            "total": len(jobs),
        }

    def setSelected(self, idx, selected):
        idx = int(idx)
        if 0 <= idx < len(self._jobs):
            j = self._jobs[idx]
            if j.status == "pending":
                j.selected = bool(selected)
        return True

    def cancelSend(self):
        self._cancel_flag.set()
        return True

    def sendSelected(self, app_pw_raw: str, indices=None) -> bool:
        pw = _normalize_app_password(app_pw_raw)
        if len(pw) != 16:
            raise RuntimeError(
                f"App Password 長度應為 16 碼（去空白後為 {len(pw)} 碼）")
        if not self._sender_email:
            raise RuntimeError("請先填入寄件 Gmail")
        if self._send_thread and self._send_thread.is_alive():
            raise RuntimeError("已有寄送任務進行中")

        # 用前端傳來的 indices 做唯一依據，避免 setSelected 與 sendSelected
        # 之間的 race condition 造成跳寄。
        if indices is None:
            targets = [(i, j) for i, j in enumerate(self._jobs)
                       if j.selected and j.status == "pending"]
        else:
            targets = []
            seen = set()
            for raw_idx in indices:
                try:
                    ix = int(raw_idx)
                except (TypeError, ValueError):
                    continue
                if ix in seen:
                    continue
                seen.add(ix)
                if 0 <= ix < len(self._jobs):
                    j = self._jobs[ix]
                    if j.status == "pending":
                        targets.append((ix, j))
        if not targets:
            raise RuntimeError("沒有可寄送的項目")

        self._cancel_flag.clear()

        def worker():
            total = len(targets)
            sent = failed = 0
            for n, (i, j) in enumerate(targets, 1):
                if self._cancel_flag.is_set():
                    _log("⛔ 使用者中止寄送")
                    break
                _log(f"[{n}/{total}] 寄給 {j.person_name} <{j.to_email}>…")
                _progress(n - 1, total,
                          f"寄給 {j.person_name}（{n}/{total}）")
                try:
                    send_via_gmail_smtp(self._sender_email, pw, j)
                    sent += 1
                    _log("  ✓ 已寄出")
                    emit("job-update", _job_to_dict(j, i))
                except SmtpAuthError as e:
                    failed += 1
                    _log("  ✗ 認證失敗，停止整批寄送")
                    emit("job-update", _job_to_dict(j, i))
                    emit("send-error", {
                        "title": "Gmail 認證失敗",
                        "message": str(e),
                    })
                    break
                except Exception as e:
                    failed += 1
                    _log(f"  ✗ 失敗：{e}")
                    emit("job-update", _job_to_dict(j, i))
                if n < total and not self._cancel_flag.is_set():
                    time.sleep(SEND_INTERVAL_SECONDS)

            _progress(total, total, "寄送結束")
            emit("send-finished", {
                "sent": sent, "failed": failed, "total": total,
            })
            _log(f"\n寄送結束：成功 {sent} 封，失敗 {failed} 封\n")

        self._send_thread = threading.Thread(target=worker, daemon=True)
        self._send_thread.start()
        return True

    def previewToReviewer(
        self, app_pw_raw: str, reviewer_email: str, idx=None
    ) -> dict:
        """把待寄資料中隨機抽樣寄給計畫人員預審。

        - 多位 reviewer → 每位收到「不同樣本」(同一筆 job 不會同時寄給兩位)
        - 樣本選取:先按費用類別分桶,每個桶抽一筆 → 達成「各種費用各一」
        - 每封信附件、內文跟該樣本人員將實際收到的完全一致,
          只在 body 最上方多一段預審說明、主旨前綴 [預審-請確認｜類別]
        - 原 jobs 狀態完全不受影響
        - idx 參數保留(舊呼叫相容),但會被忽略 — 現在一律隨機抽
        """
        pw = _normalize_app_password(app_pw_raw)
        if len(pw) != 16:
            raise RuntimeError(
                f"App Password 長度應為 16 碼（去空白後為 {len(pw)} 碼）")
        if not self._sender_email:
            raise RuntimeError("請先填入寄件 Gmail")

        # 支援多位 reviewer:逗號 / 分號 / 空白(含全形)皆可當分隔
        # 並順手把 email 字串中的不可見字元(NBSP、零寬空白等)清掉
        raw = (reviewer_email or "")
        for ch in (" ", "​", "‌", "‍", "﻿", "　"):
            raw = raw.replace(ch, " ")
        addrs: list[str] = []
        for part in re.split(r"[,;\s]+", raw):
            # 強制移除段內所有空白字元(含 NBSP、ZWSP、全形空白…),
            # 避免 is_valid_email_format 把不可見空白誤判為「含空白」。
            e = "".join(c for c in part if not c.isspace())
            if not e or e in addrs:
                continue
            addrs.append(e)
        if not addrs:
            raise RuntimeError("請先填入計畫人員 Email")
        for e in addrs:
            ok, reason = is_valid_email_format(e)
            if not ok:
                dump = " ".join(f"U+{ord(c):04X}" for c in e)
                raise RuntimeError(
                    f"計畫人員 Email「{e}」格式不正確：{reason}"
                    f"（codepoints: {dump}）")
        reviewer = ", ".join(addrs)

        samples = _pick_samples_for_reviewers(self._jobs, len(addrs))
        if not samples:
            raise RuntimeError(
                "沒有可預審的項目（請先勾選至少一筆待寄人員）")

        sent_samples: list[dict] = []
        failed: list[dict] = []
        for i, addr in enumerate(addrs):
            src = samples[i] if i < len(samples) else samples[-1]
            cat = _job_main_category(src) or "綜合"
            preview = copy.copy(src)
            preview.to_email = addr
            preview.subject = f"[預審-請確認｜{cat}] {src.subject}"
            preview.body = (
                f"⚠️ 這是寄給所有人前的預審信件\n"
                f"樣本人員:{src.person_name} <{src.to_email}>\n"
                f"附件主類別:{cat}\n"
                f"附件、主旨、內文皆與該名收件人將實際收到的完全一致。\n"
                f"（多位計畫人員預審時,每位拿到的樣本可能不同,"
                f"系統會盡量讓不同費用類別各被預審到一次）\n"
                f"\n"
                f"請計畫人員協助確認以下三點:\n"
                f"  1. 信件內容是否需要更正、錯誤、或補充訊息?\n"
                f"  2. 信件中的「領據填寫範例」連結是否可正常點閱?\n"
                f"  3. 附件 PDF 是否需要密碼?\n"
                f"     使用通用密碼或身分證字號是否可正常開啟?\n"
                f"\n"
                f"確認無誤後,請回覆寄送者以繼續批次寄送。\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"\n"
            ) + (src.body or "")
            preview.status = "pending"
            preview.selected = True

            _log(
                f"📧 [{i+1}/{len(addrs)}] 寄預審至 {addr}"
                f"（樣本：{src.person_name} · {cat}）"
            )
            try:
                send_via_gmail_smtp(self._sender_email, pw, preview)
                _log("  ✓ 預審信已寄出")
                sent_samples.append({
                    "reviewer": addr,
                    "sample_idx": self._jobs.index(src),
                    "sample_name": src.person_name,
                    "sample_email": src.to_email,
                    "category": cat,
                })
            except SmtpAuthError:
                raise
            except Exception as e:
                _log(f"  ✗ 預審寄送失敗：{e}")
                failed.append({"reviewer": addr, "err": str(e)})

            if i < len(addrs) - 1:
                time.sleep(SEND_INTERVAL_SECONDS)

        if not sent_samples:
            err = (failed[0].get("err") if failed else "未知錯誤")
            raise RuntimeError(f"預審寄送全部失敗：{err}")

        return {
            "ok": True,
            "reviewer": reviewer,
            "reviewers": addrs,
            "samples": sent_samples,
            "failed": failed,
        }

    def sendOne(self, app_pw_raw: str, idx) -> dict:
        idx = int(idx)
        pw = _normalize_app_password(app_pw_raw)
        if len(pw) != 16:
            raise RuntimeError(
                f"App Password 長度應為 16 碼（去空白後為 {len(pw)} 碼）")
        if not self._sender_email:
            raise RuntimeError("請先填入寄件 Gmail")
        if not (0 <= idx < len(self._jobs)):
            raise RuntimeError("索引超出範圍")
        j = self._jobs[idx]
        if j.status != "pending":
            raise RuntimeError(f"此項目狀態為 {j.status}，無法重寄")
        try:
            send_via_gmail_smtp(self._sender_email, pw, j)
            _log(f"✓ 單筆寄出 {j.person_name}")
        except SmtpAuthError as e:
            j.status = "failed"; j.error = str(e)
            raise
        return _job_to_dict(j, idx)


api = EmailSenderApi()


# ─── HTTP server ───
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, *a, **k):
        pass

    def end_headers(self):
        # 防止瀏覽器 cache 舊版 HTML / JS / CSS
        self.send_header("Cache-Control",
                         "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def _serve_events(self):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = _event_q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                payload = (
                    f"event: {msg['event']}\n"
                    f"data: {json.dumps(msg['data'], ensure_ascii=False)}\n\n"
                ).encode("utf-8")
                self.wfile.write(payload)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError,
                ConnectionAbortedError, OSError):
            return
        except Exception:
            traceback.print_exc()
            return

    def _json_response(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/api/events":
            return self._serve_events()
        if url.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if url.path == "/" or url.path == "":
            # 把 / 對到 HTML（中文檔名須 URL-encode 給 SimpleHTTPRequestHandler）
            self.path = "/" + urllib.parse.quote("Gmail 寄送器.html")
        return super().do_GET()

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if not url.path.startswith("/api/"):
            self.send_error(404, "Not Found")
            return
        name = url.path[len("/api/"):]
        ln = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(ln) if ln else b""
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            body = {}
        args = body.get("args", [])

        if not hasattr(api, name) or name.startswith("_"):
            return self._json_response(404, {"err": f"unknown api: {name}"})
        try:
            fn = getattr(api, name)
            result = fn(*args)
            return self._json_response(200, {"ok": True, "result": result})
        except Exception as e:
            traceback.print_exc()
            return self._json_response(
                200, {"ok": False, "err": str(e)})


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    httpd = ThreadedHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"\nGmail 寄送器 2.0.2 — 已啟動於 http://127.0.0.1:{PORT}\n")
    print("（請保留此視窗。關掉視窗 = 關掉程式）\n")

    def serve():
        try:
            httpd.serve_forever()
        except Exception:
            traceback.print_exc()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    # 主 thread 跑 Tk mainloop（處理選檔 / 選資料夾對話框）
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.after(50, lambda: _dialog_pump(root))
        # mainloop 啟動後再開瀏覽器，確保對話框 pump 已 ready
        # URL 加 timestamp 強制 cache miss
        boot_url = f"http://127.0.0.1:{PORT}/?t={int(time.time())}"
        root.after(200, lambda: webbrowser.open(boot_url))
        root.mainloop()
    except Exception:
        traceback.print_exc()
        print("[警告] tkinter 無法啟動，選檔功能將無法使用，其餘功能仍可運作")
        webbrowser.open(f"http://127.0.0.1:{PORT}/?t={int(time.time())}")
        try:
            t.join()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
