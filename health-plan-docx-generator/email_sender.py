"""Gmail 寄送模組 — 掃描合併 PDF、對應人員個資、透過 SMTP 寄送

用法：
    jobs = build_email_jobs(month_dir, receipt_lookup, 115, 4)
    for job in jobs:
        if job.selected and job.status == "pending":
            send_via_gmail_smtp(sender, app_pw, job)
"""

from __future__ import annotations

import glob
import os
import smtplib
import ssl
from dataclasses import dataclass, field
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from models import ReceiptInfo


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # SSL

# Gmail 官方附件上限 25 MB（含 MIME 編碼後）
# base64 會放大約 1.37 倍，所以原始檔案留 18 MB 緩衝
ATTACHMENT_SIZE_LIMIT_BYTES = 18 * 1024 * 1024


@dataclass
class EmailJob:
    """單封信的寄送工作。"""
    person_name: str
    role: str
    clinic_name: str
    to_email: str
    subject: str
    body: str
    attachments: list[str] = field(default_factory=list)  # 絕對路徑
    selected: bool = True
    status: str = "pending"  # pending / sent / failed / skipped
    error: str = ""

    @property
    def total_attachment_bytes(self) -> int:
        total = 0
        for p in self.attachments:
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
        return total

    @property
    def is_sendable(self) -> bool:
        """可寄送 = 有 Email、有附件、尚未寄出。"""
        return (
            self.status == "pending"
            and bool(self.to_email)
            and bool(self.attachments)
        )


# ──────────────────────────────────────────────────────────
# Subject / Body 模板
# ──────────────────────────────────────────────────────────

def build_subject(roc_year: int, roc_month: int, clinic_name: str) -> str:
    """主旨：{民國年月} 健康台灣深耕計畫核銷文件 — {診所名}"""
    month_str = f"{roc_year}年{roc_month:02d}月"
    clinic = clinic_name or "（未填所屬診所）"
    return f"{month_str} 健康台灣深耕計畫核銷文件 — {clinic}"


def build_body(
    person_name: str,
    role: str,
    clinic_name: str,
    roc_year: int,
    roc_month: int,
    attachments: list[str],
) -> str:
    """根據附件檔名自動列出內容。"""
    month_str = f"{roc_year}年{roc_month:02d}月"
    name = person_name or "您"
    role_text = role or ""
    clinic_text = clinic_name or ""

    # 附件描述清單
    attachment_lines = []
    for idx, path in enumerate(attachments, 1):
        filename = os.path.basename(path)
        desc = _describe_attachment(path)
        if desc:
            attachment_lines.append(f"  {idx}. {desc}（{filename}）")
        else:
            attachment_lines.append(f"  {idx}. {filename}")

    attachment_block = "\n".join(attachment_lines) if attachment_lines else "  （無附件）"

    greeting = f"{name} {role_text} 您好：" if role_text else f"{name} 您好："
    clinic_line = f"附上 {clinic_text} {month_str} 健康台灣深耕計畫核銷文件，煩請查收。" \
        if clinic_text else f"附上 {month_str} 健康台灣深耕計畫核銷文件，煩請查收。"

    return (
        f"{greeting}\n"
        f"\n"
        f"{clinic_line}\n"
        f"\n"
        f"本次附件（共 {len(attachments)} 份）：\n"
        f"{attachment_block}\n"
        f"\n"
        f"如有任何問題請與本會聯繫，謝謝。\n"
        f"\n"
        f"— 台北市醫師公會\n"
    )


def _describe_attachment(pdf_path: str) -> str:
    """依 PDF 所在的類別資料夾推斷用途描述。

    路徑範例：
      .../處方費領據/PDF/王大明.pdf        → 處方費領據
      .../處方執行費領據/PDF/王大明.pdf     → 處方執行費領據
      .../處方處置費領據/PDF/運動處方/王大明.pdf → 處方處置費領據（運動處方）
      .../健康管理費領據/PDF/王大明.pdf     → 健康管理費領據
    """
    parts = os.path.normpath(pdf_path).split(os.sep)
    # 找「PDF」前一層作為類別
    try:
        pdf_idx = parts.index("PDF")
    except ValueError:
        return ""
    if pdf_idx == 0:
        return ""
    category = parts[pdf_idx - 1]

    # 處方處置費領據會再多一層處方類型
    subtype = ""
    if pdf_idx + 2 < len(parts):  # PDF / 處方類型 / 姓名.pdf
        candidate = parts[pdf_idx + 1]
        if candidate.endswith("處方"):
            subtype = candidate

    return f"{category}（{subtype}）" if subtype else category


# ──────────────────────────────────────────────────────────
# 掃描輸出資料夾 → 建立 EmailJob 列表
# ──────────────────────────────────────────────────────────

def build_email_jobs(
    month_dir: str,
    receipt_lookup: dict[str, ReceiptInfo],
    roc_year: int,
    roc_month: int,
) -> list[EmailJob]:
    """掃描 month_dir 下所有合併 PDF，以姓名分組組成 EmailJob 列表。

    姓名對應規則：PDF 檔名（不含副檔名）= 人員姓名
    收件資料查 receipt_lookup[姓名]
    缺 Email 或查無人員仍會產生一筆 EmailJob，但 status='skipped'
    """
    if not month_dir or not os.path.isdir(month_dir):
        return []

    # 遞迴找所有 *領據/PDF/.../*.pdf
    # 資料夾名稱為「處方費領據 / 處方執行費領據 / 處方處置費領據 / 健康管理費領據」
    # 使用 glob 的 ** 遞迴模式以支援「分區」子資料夾結構
    pdfs: list[str] = []
    for pdf_path in glob.glob(
        os.path.join(month_dir, "**", "*領據", "PDF", "**", "*.pdf"),
        recursive=True,
    ):
        pdfs.append(os.path.abspath(pdf_path))

    # 依「姓名」分組（檔名去掉 .pdf）
    by_person: dict[str, list[str]] = {}
    for p in pdfs:
        stem = os.path.splitext(os.path.basename(p))[0].strip()
        if not stem:
            continue
        by_person.setdefault(stem, []).append(p)

    jobs: list[EmailJob] = []
    for name in sorted(by_person.keys()):
        files = sorted(by_person[name])
        info = receipt_lookup.get(name)

        role = info.role if info else ""
        clinic = info.clinic_name if info else ""
        email = (info.email if info else "").strip()

        subject = build_subject(roc_year, roc_month, clinic)
        body = build_body(name, role, clinic, roc_year, roc_month, files)

        job = EmailJob(
            person_name=name,
            role=role,
            clinic_name=clinic,
            to_email=email,
            subject=subject,
            body=body,
            attachments=files,
            selected=True,
            status="pending",
        )

        # 判斷是否可寄
        if not info:
            job.status = "skipped"
            job.error = "個資缺漏（人員個資.xlsx 查無此姓名）"
            job.selected = False
        elif not email:
            job.status = "skipped"
            job.error = "無 Email（請補填人員個資.xlsx Email 欄）"
            job.selected = False
        elif not files:
            job.status = "skipped"
            job.error = "無附件"
            job.selected = False

        jobs.append(job)

    return jobs


# ──────────────────────────────────────────────────────────
# SMTP 寄送
# ──────────────────────────────────────────────────────────

class SmtpAuthError(RuntimeError):
    """SMTP 認證失敗（App Password 錯誤 / 兩步驟未開）。"""


def _build_message(
    sender_email: str,
    job: EmailJob,
) -> MIMEMultipart:
    msg = MIMEMultipart("mixed")
    msg["From"] = formataddr(("台北市醫師公會", sender_email))
    msg["To"] = job.to_email
    msg["Subject"] = job.subject

    msg.attach(MIMEText(job.body, "plain", "utf-8"))

    for path in job.attachments:
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            part = MIMEBase("application", "pdf")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        # 附件檔名以 UTF-8 處理（中文姓名）
        filename = os.path.basename(path)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=("utf-8", "", filename),
        )
        msg.attach(part)

    return msg


def send_via_gmail_smtp(
    sender_email: str,
    app_password: str,
    job: EmailJob,
) -> None:
    """寄送單一 EmailJob。

    成功 → job.status = 'sent'
    認證失敗 → 拋 SmtpAuthError（上層應停止整批）
    其他失敗 → job.status = 'failed', job.error 紀錄原因
    """
    if not job.is_sendable:
        return

    try:
        msg = _build_message(sender_email, job)
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=60) as server:
            try:
                server.login(sender_email, app_password)
            except smtplib.SMTPAuthenticationError as e:
                raise SmtpAuthError(
                    "Gmail 認證失敗，請確認：\n"
                    "1. 使用的是 App Password（非一般密碼）\n"
                    "2. 寄件者帳號已開啟兩步驟驗證\n"
                    f"\n原始錯誤：{e}"
                )
            server.send_message(msg)
        job.status = "sent"
        job.error = ""
    except SmtpAuthError:
        job.status = "failed"
        job.error = "Gmail 認證失敗"
        raise
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
