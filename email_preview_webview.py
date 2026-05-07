"""Gmail 寄送預覽 — webview 視窗版（取代 customtkinter 那版 EmailPreviewWindow）。"""

import os
import sys
import time
import threading
import webview

from email_sender import (
    EmailJob, SmtpAuthError, send_via_gmail_smtp,
)

if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WEB_DIR = os.path.join(BASE_DIR, "web_ui")

SEND_INTERVAL_SECONDS = 1.5

_INVISIBLE_ORDS = {0x200B, 0x200C, 0x200D, 0xFEFF, 0x3000, 0x00A0}


def _normalize_app_password(raw):
    cleaned = []
    for c in raw:
        if c.isspace():
            continue
        if ord(c) in _INVISIBLE_ORDS:
            continue
        if 32 < ord(c) < 127:
            cleaned.append(c)
    return "".join(cleaned)


def _job_to_dict(j):
    return {
        "person_name": j.person_name,
        "role": j.role,
        "clinic_name": j.clinic_name or "",
        "to_email": j.to_email or "",
        "zone": j.zone or "",
        "status": j.status,
        "error": j.error or "",
        "attachments_count": len(j.attachments),
        "selected": j.selected,
    }


class EmailApi:
    def __init__(self, jobs, sender):
        self.jobs = jobs
        self.sender = sender
        self.window = None

    def getEmailData(self):
        return {
            "sender": self.sender,
            "jobs": [_job_to_dict(j) for j in self.jobs],
        }

    def sendBatch(self, app_pw_raw, indices):
        pw = _normalize_app_password(app_pw_raw)
        sent = failed = 0
        for idx in indices:
            j = self.jobs[idx]
            if j.status == "sent":
                continue
            if not j.to_email or not j.attachments:
                j.status = "skipped"
                continue
            try:
                send_via_gmail_smtp(self.sender, pw, j)
                j.status = "sent"
                sent += 1
            except SmtpAuthError as e:
                j.status = "failed"
                j.error = "認證失敗：" + str(e)
                failed += 1
                # 認證失敗就不繼續了
                break
            except Exception as e:
                j.status = "failed"
                j.error = str(e)
                failed += 1
            time.sleep(SEND_INTERVAL_SECONDS)
        return {
            "sent": sent, "failed": failed,
            "jobs": [_job_to_dict(x) for x in self.jobs],
        }


def open_email_preview(jobs, sender):
    """開新 webview 視窗。"""
    api = EmailApi(jobs, sender)
    html = os.path.join(WEB_DIR, "email_preview.html")
    win = webview.create_window(
        "📧 Gmail 寄送預覽",
        url=html, js_api=api,
        width=1080, height=720, min_size=(960, 520))
    api.window = win
