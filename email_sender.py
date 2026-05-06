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
import re
import smtplib
import ssl
import sys
from dataclasses import dataclass, field
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from models import ReceiptInfo


# 簡單的 Email 格式驗證:抓常見 typo 比方 gmail..com、缺 @、缺網域 .tw 等。
# 原則:在掃描階段就把格式錯的標成 skipped,免得白白吃掉一次 Gmail SMTP。
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$"
)


def is_valid_email_format(email: str) -> tuple[bool, str]:
    """回傳 (是否合法, 不合法時的原因說明)。"""
    if not email:
        return False, "空字串"
    e = email.strip()
    if " " in e:
        return False, "含空白"
    if ".." in e:
        return False, "含連續兩個點 (..)"
    if e.count("@") != 1:
        return False, "@ 必須剛好出現一次"
    local, _, domain = e.partition("@")
    if not local:
        return False, "@ 前空白"
    if not domain or "." not in domain:
        return False, "網域格式不對 (例:缺 .com)"
    if not _EMAIL_RE.match(e):
        return False, "格式不符 (含奇怪字元或缺失片段)"
    return True, ""


# 固定附件:領據填寫範例
RECEIPT_TEMPLATE_FILENAME = "領據填寫範例.pdf"
# 社區駐點辦公室收件地址(信件內文用)
OFFICE_ADDRESS = "台北市北投區中央南路一段45號-1"
# 聯絡資訊
CONTACT_PHONE = "(02)2891-7453"
CONTACT_EMAIL = "tpma.healthtw@gmail.com"


def find_receipt_template_pdf() -> str | None:
    """尋找領據填寫範本 PDF。
    打包後：sys._MEIPASS/word_templates/ 或 exe 同目錄
    開發時：本檔旁的 word_templates/
    回傳絕對路徑或 None。
    """
    candidates: list[str] = []
    if getattr(sys, "frozen", False):
        # PyInstaller 打包後
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(os.path.join(
                meipass, "word_templates", RECEIPT_TEMPLATE_FILENAME))
        # 允許使用者放一份在 exe 同目錄覆蓋
        candidates.append(os.path.join(
            os.path.dirname(sys.executable), RECEIPT_TEMPLATE_FILENAME))
    else:
        candidates.append(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "word_templates", RECEIPT_TEMPLATE_FILENAME))

    for p in candidates:
        if os.path.isfile(p):
            return os.path.abspath(p)
    return None


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

    # 寄送前重建 body 用的上下文(讓 body 跟 attachments 永遠對得上)
    roc_year: int = 0
    roc_month: int = 0
    template_drive_link: str = ""
    extra_message: str = ""

    # 該人員屬於哪一區(中山/北投/士林/課程老師…),預覽視窗用來分組篩選
    zone: str = ""

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
    """主旨格式:【健康台灣深耕計畫】{診所名} {民國年}年{月}月份核銷文件寄送通知

    若沒填診所就直接省略,不要塞 (未填所屬診所) 之類的佔位符到正式郵件主旨。
    """
    if clinic_name:
        return (f"【健康台灣深耕計畫】{clinic_name} "
                f"{roc_year}年{roc_month}月份核銷文件寄送通知")
    return f"【健康台灣深耕計畫】{roc_year}年{roc_month}月份核銷文件寄送通知"


def build_body(
    person_name: str,
    role: str,
    clinic_name: str,
    roc_year: int,
    roc_month: int,
    attachments: list[str],
    template_drive_link: str = "",
    extra_message: str = "",
) -> str:
    """根據附件檔名自動列出內容。

    template_drive_link 非空時:範本 PDF 不會在 attachments 中(由
    build_email_jobs 處理),信中改放連結讓收件者自行下載。

    extra_message 非空時會插在問候之後、附件清單之前,以「補充說明」
    區塊呈現,適合用來通知所有收件人本次的特殊事項。
    """
    month_str = f"{roc_year}年{roc_month}月"
    name = person_name or "您"
    role_text = role or ""
    clinic_text = clinic_name or ""

    # 附件描述清單(每一份都要清楚寫出是哪一類的 PDF,
    # 多份相同檔名(X_明細領據.pdf)時不論從檔名還是描述都能區分)
    attachment_lines = []
    for idx, path in enumerate(attachments, 1):
        # body 顯示的檔名要跟收件人在 Gmail 看到的實際附件檔名一致
        display_name = _attached_filename(path)
        original = os.path.basename(path)
        if original == RECEIPT_TEMPLATE_FILENAME:
            attachment_lines.append(
                f"{idx}. {display_name} — 欄位填寫方式說明,供 貴診所參考")
        else:
            category = _describe_attachment(path)
            if category:
                attachment_lines.append(
                    f"{idx}. {display_name} — 【{category}】 待填寫之核銷文件")
            else:
                attachment_lines.append(
                    f"{idx}. {display_name} — 待填寫之核銷文件")
    attachment_block = "\n".join(attachment_lines) if attachment_lines else ""

    greeting = f"{name} {role_text} 您好:" if role_text else f"{name} 您好:"
    if clinic_text:
        intro = (f"附上 {clinic_text} {month_str}份「健康台灣深耕計畫」"
                 f"核銷文件,煩請查收。")
    else:
        intro = (f"附上 {month_str}份「健康台灣深耕計畫」"
                 f"核銷文件,煩請查收。")

    # 範例 PDF 的引用 — 有 Drive 連結就用連結,否則指附件中的檔案
    if template_drive_link:
        template_section = (
            f"【領據填寫範例】\n"
            f"請點以下連結下載「領據填寫範例.pdf」,內含每個欄位填寫方式說明:\n"
            f"{template_drive_link}\n"
            f"\n"
        )
        instruction_intro = "請參考上述「領據填寫範例」"
    else:
        template_section = ""
        instruction_intro = f"請參考「{RECEIPT_TEMPLATE_FILENAME}」之說明"

    extra_block = ""
    if extra_message and extra_message.strip():
        extra_block = (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 補充說明\n"
            f"{extra_message.strip()}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
        )

    return (
        f"{greeting}\n"
        f"\n"
        f"{intro}\n"
        f"\n"
        f"{extra_block}"
        f"【本次附件】(共 {len(attachments)} 份)\n"
        f"{attachment_block}\n"
        f"\n"
        f"{template_section}"
        f"【填寫與寄回說明】\n"
        f"{instruction_intro}完成填寫與用印後,"
        f"以紙本寄回下列地址:\n"
        f"\n"
        f"健康台灣深耕計畫社區駐點辦公室\n"
        f"  {OFFICE_ADDRESS}\n"
        f"\n"
        f"煩請於(下週四)前寄回,以利本會核銷作業。\n"
        f"\n"
        f"如有任何問題,歡迎來電 {CONTACT_PHONE} 或 Email 至 {CONTACT_EMAIL}\n"
        f"與本會聯繫。\n"
        f"\n"
        f"謝謝您的配合!\n"
        f"\n"
        f"— 台北市醫師公會\n"
        f"   健康台灣深耕計畫工作小組\n"
    )


def _attached_filename(pdf_path: str) -> str:
    """寄送時附件實際使用的檔名。

    多個檔案同名(都叫 X_明細領據.pdf 但分屬不同類別資料夾)時,
    把類別補進檔名後綴避免在收件人 Gmail 附件區看到一堆同名檔案
    撞檔下載。範本 PDF 維持原檔名。
    """
    filename = os.path.basename(pdf_path)
    if filename == RECEIPT_TEMPLATE_FILENAME:
        return filename
    category = _describe_attachment(pdf_path)
    if not category:
        return filename
    stem, ext = os.path.splitext(filename)
    # 把全形括號改成可在大多數 mail client 正常顯示的下底線
    safe_cat = (category
                .replace("（", "_")
                .replace("）", "")
                .replace("(", "_")
                .replace(")", ""))
    return f"{stem}_{safe_cat}{ext}"


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
    template_drive_link: str = "",
    extra_message: str = "",
    allowed_zones: list[str] | None = None,
) -> list[EmailJob]:
    """掃描 month_dir 下所有合併 PDF，以姓名分組組成 EmailJob 列表。

    姓名對應規則：PDF 檔名（不含副檔名）= 人員姓名
    收件資料查 receipt_lookup[姓名]
    缺 Email 或查無人員仍會產生一筆 EmailJob，但 status='skipped'

    allowed_zones：None 或空 list 代表掃整個 month_dir(所有區別都收);
        指定後只掃 month_dir/{zone}/... 各個區別子資料夾,
        其他區的 PDF 完全不出現在預覽清單裡。
    """
    if not month_dir or not os.path.isdir(month_dir):
        return []

    # 遞迴找所有 *領據/{姓名}_明細領據.pdf(合併版的最終檔)
    # 資料夾名稱為「處方處方費與處方執行費領據 / 處方處置費領據 / 健康管理費領據」
    # 使用 glob 的 ** 遞迴模式以支援「分區」子資料夾結構
    pdfs: list[str] = []
    # 同時記錄每個 PDF 屬於哪一區(月份資料夾下的第一層子資料夾)
    zone_by_path: dict[str, str] = {}

    def _zone_from_path(p: str) -> str:
        try:
            rel = os.path.relpath(p, month_dir)
        except ValueError:
            return ""
        parts = rel.split(os.sep)
        return parts[0] if len(parts) >= 2 else ""

    if allowed_zones:
        for zone in allowed_zones:
            zone_dir = os.path.join(month_dir, zone)
            if not os.path.isdir(zone_dir):
                continue
            for pdf_path in glob.glob(
                os.path.join(zone_dir, "**", "*領據", "*_明細領據.pdf"),
                recursive=True,
            ):
                abs_path = os.path.abspath(pdf_path)
                pdfs.append(abs_path)
                zone_by_path[abs_path] = zone
    else:
        for pdf_path in glob.glob(
            os.path.join(month_dir, "**", "*領據", "*_明細領據.pdf"),
            recursive=True,
        ):
            abs_path = os.path.abspath(pdf_path)
            pdfs.append(abs_path)
            zone_by_path[abs_path] = _zone_from_path(abs_path)

    # 依「姓名」分組(檔名 = {姓名}_明細領據.pdf,去掉 _明細領據 後綴)
    SUFFIX = "_明細領據"
    by_person: dict[str, list[str]] = {}
    for p in pdfs:
        stem = os.path.splitext(os.path.basename(p))[0].strip()
        if stem.endswith(SUFFIX):
            stem = stem[:-len(SUFFIX)].strip()
        if not stem:
            continue
        # 排除「領據填寫範本」本身(若被放進 month_dir 則會被誤抓)
        if stem == os.path.splitext(RECEIPT_TEMPLATE_FILENAME)[0]:
            continue
        by_person.setdefault(stem, []).append(p)

    # 找範本 PDF(若有 Drive 連結就不附,改在內文放連結)
    template_pdf = find_receipt_template_pdf()

    jobs: list[EmailJob] = []
    for name in sorted(by_person.keys()):
        files = sorted(by_person[name])
        # 該人員所屬的區別:從 PDF 路徑反推。範例 PDF (template_pdf) 不算區。
        zones_for_person = sorted({
            zone_by_path.get(f, "") for f in files if f in zone_by_path
        } - {""})
        person_zone = "、".join(zones_for_person) if zones_for_person else ""

        if template_pdf and not template_drive_link:
            files.append(template_pdf)
        info = receipt_lookup.get(name)

        role = info.role if info else ""
        clinic = info.clinic_name if info else ""
        email = (info.email if info else "").strip()

        subject = build_subject(roc_year, roc_month, clinic)
        body = build_body(name, role, clinic, roc_year, roc_month, files,
                          template_drive_link=template_drive_link,
                          extra_message=extra_message)

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
            # 寄送前重建 body 用
            roc_year=roc_year,
            roc_month=roc_month,
            template_drive_link=template_drive_link,
            extra_message=extra_message,
            zone=person_zone,
        )

        # 判斷是否可寄
        if not info:
            job.status = "skipped"
            job.error = "個資缺漏(人員個資.xlsx 查無此姓名)"
            job.selected = False
        elif not email:
            job.status = "skipped"
            job.error = "無 Email(請補填人員個資.xlsx Email 欄)"
            job.selected = False
        elif not files:
            job.status = "skipped"
            job.error = "無附件"
            job.selected = False
        else:
            ok, reason = is_valid_email_format(email)
            if not ok:
                # 在送出前先擋掉格式錯誤的 Email,
                # 不浪費一次 Gmail SMTP 嘗試(否則 Gmail 會回 553 5.1.3)。
                job.status = "skipped"
                job.error = (f"Email 格式不正確:{reason}"
                             f"(請修正人員個資.xlsx → {email})")
                job.selected = False

        if job.status == "pending":
            # 預檢:附件總大小超過 Gmail 限制就直接跳過
            total = job.total_attachment_bytes
            if total > ATTACHMENT_SIZE_LIMIT_BYTES:
                size_mb = total / 1024 / 1024
                job.status = "skipped"
                job.error = (f"附件 {size_mb:.1f} MB 超過 Gmail 18 MB 上限,"
                             f"請手動分批寄送或壓縮 PDF")
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
        # 用 _attached_filename:同一封信若有多份同檔名 PDF 會自動加上
        # 類別後綴避免撞名(收件人下載時不會被覆蓋)
        filename = _attached_filename(path)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=("utf-8", "", filename),
        )
        msg.attach(part)

    return msg


_BODY_COUNT_RE = re.compile(r"【本次附件】\(共\s*(\d+)\s*份\)")


def _ensure_body_matches_attachments(job: EmailJob) -> None:
    """寄送前最後一道保險:確保 body 中的「共 N 份」跟附件清單跟實際 attachments 完全一致。

    可能對不上的歷史原因:
      - v28 之前的「📢 套用至全部」會把 A 的 body 整段複製到 B,
        但 B 的 attachments 沒換 → 兩邊走鐘
      - 中間 Drive 連結被改過,但某些 job 是更早 build 的
      - 任何一個沒料到的殘留資料

    只要偵測到內文宣告的份數跟 len(attachments) 不一致,就用 job 上面
    存的 roc_year / template_drive_link 等上下文,以「附件為準」整段重建 body。
    """
    if not job.attachments:
        return
    if not job.roc_year or not job.roc_month:
        return  # 舊版 job 沒有上下文,只能照原樣寄
    m = _BODY_COUNT_RE.search(job.body or "")
    if m and int(m.group(1)) == len(job.attachments):
        return  # 已一致,不動 body(保留使用者可能的手動編輯)

    # 不一致 → 以 attachments 為準重建 body
    job.body = build_body(
        person_name=job.person_name,
        role=job.role,
        clinic_name=job.clinic_name,
        roc_year=job.roc_year,
        roc_month=job.roc_month,
        attachments=job.attachments,
        template_drive_link=job.template_drive_link,
        extra_message=job.extra_message,
    )


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

    # 出信前先做最後一道一致性檢查(內文裡的「共 N 份」必須等於 attachments 長度)
    _ensure_body_matches_attachments(job)

    try:
        msg = _build_message(sender_email, job)
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT,
                              context=context, timeout=60) as server:
            try:
                server.login(sender_email, app_password)
            except smtplib.SMTPAuthenticationError as e:
                raise SmtpAuthError(
                    "Gmail 認證失敗 (帳號密碼錯誤),請確認:\n"
                    "1. 使用的是 App Password (非一般 Gmail 密碼)\n"
                    "2. 寄件者帳號已開啟兩步驟驗證\n"
                    "3. App Password 為 16 碼小寫英文(複製時不要含空白)\n"
                    f"\n原始錯誤:{e}"
                )
            except smtplib.SMTPServerDisconnected as e:
                # Google 在認證階段直接斷線,通常是 App Password 錯
                # 或帳號被暫時擋(IP/頻率)。
                raise SmtpAuthError(
                    "SMTP 連線在認證時被 Google 斷開。最常見原因:\n"
                    "1. App Password 打錯(請重新產生一份 16 碼貼上)\n"
                    "2. 帳號未開啟兩步驟驗證,App Password 無效\n"
                    "3. 短時間嘗試太多次,被 Google 暫時擋,"
                    "等 5-10 分鐘再試\n"
                    "4. 公司網路擋了 smtp.gmail.com:465\n"
                    f"\n原始錯誤:{e}"
                )
            try:
                server.send_message(msg)
            except smtplib.SMTPDataError as e:
                size_mb = job.total_attachment_bytes / 1024 / 1024
                raise RuntimeError(
                    f"Gmail 拒絕信件(附件 {size_mb:.1f} MB):{e}")
            except smtplib.SMTPServerDisconnected as e:
                # send 階段被 Google 斷線,絕大多數是附件超過 25 MB 上限
                size_mb = job.total_attachment_bytes / 1024 / 1024
                raise RuntimeError(
                    f"附件過大 ({size_mb:.1f} MB) Gmail 主動斷線。"
                    f"Gmail 上限 25 MB(編碼後),"
                    f"建議單封 ≤ 18 MB。原始錯誤:{e}")
        job.status = "sent"
        job.error = ""
    except SmtpAuthError as e:
        job.status = "failed"
        job.error = str(e)
        raise
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
