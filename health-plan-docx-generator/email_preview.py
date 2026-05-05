"""Gmail 寄送預覽視窗 — 共用 module。
被 app.py(主產生器)和 email_sender_app.py(獨立寄送器)共用。
"""
import threading
import time
from collections import Counter

import customtkinter as ctk
from tkinter import messagebox

from email_sender import EmailJob, SmtpAuthError, send_via_gmail_smtp


MONO_FONT = "Cascadia Mono"

# 兩封信之間的間隔(秒)。確保「一封一封寄」、減少 Google 短時間
# 收到大量請求被擋的機率;只在最後一封後不需要再等。
SEND_INTERVAL_SECONDS = 1.5

# App Password 清洗時要剃掉的「空白系」字元(含零寬字元、全形空白)
# 使用 ord() 比對避免在原始碼中放入難以辨識的零寬字元。
_INVISIBLE_ORDS = {
    0x200B,  # ZERO WIDTH SPACE
    0x200C,  # ZERO WIDTH NON-JOINER
    0x200D,  # ZERO WIDTH JOINER
    0xFEFF,  # ZERO WIDTH NO-BREAK SPACE
    0x3000,  # IDEOGRAPHIC SPACE (全形空白)
    0x00A0,  # NO-BREAK SPACE
}


def _normalize_app_password(raw: str) -> str:
    """清洗使用者貼上的 Gmail App Password。

    去掉所有空白(含全形/零寬)+ 非 ASCII 可印字元,只留下標準 16 碼。
    """
    cleaned = []
    for c in raw:
        if c.isspace():
            continue
        if ord(c) in _INVISIBLE_ORDS:
            continue
        if 32 < ord(c) < 127:
            cleaned.append(c)
    return "".join(cleaned)


class EmailPreviewWindow(ctk.CTkToplevel):
    """列出所有 EmailJob,可勾選、預覽、批次寄送。"""

    COL_WIDTHS = [(36, "☑"), (90, "區別"), (100, "姓名"), (80, "角色"),
                  (160, "診所"), (190, "Email"), (50, "附件"),
                  (240, "狀態")]

    def __init__(self, master, jobs: list[EmailJob], sender_email: str):
        super().__init__(master)
        self.title("📧 Gmail 寄送預覽")
        self.geometry("1080x680")
        self.minsize(960, 520)

        # 排序:先按區別、再按姓名,讓同一區的人聚在一起
        jobs = sorted(jobs, key=lambda j: (j.zone or "", j.person_name))
        self.jobs = jobs
        self.sender_email = sender_email
        self._row_widgets: list[dict] = []
        # 保留原始內文,讓使用者可在編輯後一鍵還原
        self._original_bodies: dict[int, str] = {id(j): j.body for j in jobs}
        # 防止重複觸發寄送(按多次按鈕、Enter 鍵連按等)
        self._sending = False

        self._build_ui()
        self._refresh_rows()

        self.after(100, self.lift)
        self.after(150, self.focus_force)

    def _build_ui(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=(15, 8))

        ctk.CTkLabel(top, text=f"寄件者: {self.sender_email}",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        ctk.CTkLabel(top, text=f"  |  共 {len(self.jobs)} 位人員",
                     text_color="#a0aec0").pack(side="left")

        ops = ctk.CTkFrame(self, fg_color="transparent")
        ops.pack(fill="x", padx=15, pady=(0, 8))

        ctk.CTkButton(ops, text="全選", width=70, height=30,
                      fg_color="gray60", hover_color="gray50",
                      command=self._select_all).pack(side="left", padx=(0, 4))
        ctk.CTkButton(ops, text="全不選", width=70, height=30,
                      fg_color="gray60", hover_color="gray50",
                      command=self._select_none).pack(side="left", padx=(0, 4))
        ctk.CTkButton(ops, text="僅選可寄送", width=90, height=30,
                      fg_color="gray60", hover_color="gray50",
                      command=self._select_sendable).pack(side="left", padx=(0, 10))

        # 依「區」勾/取消:只動該區的人,其他區保留現狀。
        # 留下你要寄的個人後再按確認寄送即可。
        zones = sorted({(j.zone or "(未分區)") for j in self.jobs})
        if zones:
            ctk.CTkLabel(ops, text="區:",
                         font=ctk.CTkFont(size=12)).pack(side="left",
                                                          padx=(4, 4))
            self.var_zone_picker = ctk.StringVar(value=zones[0])
            ctk.CTkOptionMenu(
                ops, variable=self.var_zone_picker, values=zones,
                width=110, height=30,
            ).pack(side="left", padx=(0, 4))
            ctk.CTkButton(ops, text="勾此區", width=70, height=30,
                          fg_color="#2874a6", hover_color="#1f618d",
                          command=lambda: self._toggle_zone(True)
                          ).pack(side="left", padx=(0, 4))
            ctk.CTkButton(ops, text="取消此區", width=80, height=30,
                          fg_color="gray55", hover_color="gray45",
                          command=lambda: self._toggle_zone(False)
                          ).pack(side="left", padx=(0, 4))

        self.btn_send = ctk.CTkButton(
            ops, text="✉ 確認寄送勾選項目", width=170, height=32,
            fg_color="#1e8449", hover_color="#196f3d",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_send_clicked)
        self.btn_send.pack(side="right")

        hdr = ctk.CTkFrame(self, height=30)
        hdr.pack(fill="x", padx=15)
        for i, (w, title) in enumerate(self.COL_WIDTHS):
            lbl = ctk.CTkLabel(hdr, text=title, width=w,
                               font=ctk.CTkFont(size=12, weight="bold"),
                               anchor="w")
            lbl.grid(row=0, column=i, padx=4, sticky="w")

        self.table = ctk.CTkScrollableFrame(self, height=420)
        self.table.pack(fill="both", expand=True, padx=15, pady=(4, 10))

        self.status_lbl = ctk.CTkLabel(self, text="",
                                       text_color="#a0aec0",
                                       font=ctk.CTkFont(size=11),
                                       anchor="w")
        self.status_lbl.pack(fill="x", padx=15, pady=(0, 10))

    def _refresh_rows(self):
        for w in self.table.winfo_children():
            w.destroy()
        self._row_widgets.clear()

        # 預先算出哪些 Email 被多位人員共用,用來把這些列的 Email 欄位染色
        all_emails = [j.to_email.strip().lower() for j in self.jobs
                      if j.to_email]
        dup_emails = {a for a, n in Counter(all_emails).items() if n >= 2}

        for idx, job in enumerate(self.jobs):
            row = ctk.CTkFrame(self.table,
                               fg_color=("gray92", "gray20") if idx % 2 else "transparent")
            row.pack(fill="x", pady=1)

            var = ctk.BooleanVar(value=job.selected)
            chk = ctk.CTkCheckBox(row, text="", variable=var, width=24,
                                  command=lambda j=job, v=var: self._toggle(j, v))
            chk.grid(row=0, column=0, padx=4, pady=4)

            email_norm = (job.to_email or "").strip().lower()
            email_is_dup = bool(email_norm) and email_norm in dup_emails
            email_text = job.to_email or "—"
            if email_is_dup:
                email_text = "⚠ " + email_text  # 共用信箱標記

            zone_text = job.zone or "—"
            values = [
                (90, zone_text, "#7fc4e6" if job.zone else None),
                (100, job.person_name, None),
                (80, job.role or "—", None),
                (160, job.clinic_name or "—", None),
                (190, email_text, "#d35400" if email_is_dup else None),
                (50, str(len(job.attachments)), None),
            ]
            for col_i, (w, text, color) in enumerate(values, start=1):
                kwargs = {"text": text, "width": w, "anchor": "w",
                          "font": ctk.CTkFont(size=12)}
                if color:
                    kwargs["text_color"] = color
                lbl = ctk.CTkLabel(row, **kwargs)
                lbl.grid(row=0, column=col_i, padx=4, sticky="w")

            status_lbl = ctk.CTkLabel(row, text=self._status_text(job),
                                      text_color=self._status_color(job),
                                      width=240, anchor="w",
                                      font=ctk.CTkFont(size=12))
            status_lbl.grid(row=0, column=7, padx=4, sticky="w")

            is_customized = (
                self._original_bodies.get(id(job), job.body) != job.body
            )
            btn_text = "預覽 ✎" if is_customized else "預覽"
            btn_color = ("#2874a6" if is_customized else "gray55")
            btn_hover = ("#1f618d" if is_customized else "gray45")
            btn_preview = ctk.CTkButton(
                row, text=btn_text, width=64, height=24,
                font=ctk.CTkFont(size=11),
                fg_color=btn_color, hover_color=btn_hover,
                command=lambda j=job: self._preview_job(j))
            btn_preview.grid(row=0, column=8, padx=(8, 4))

            # 失敗時加一個「錯誤詳情」按鈕,可看完整 error
            if job.status == "failed" and job.error:
                btn_err = ctk.CTkButton(
                    row, text="錯誤", width=50, height=24,
                    font=ctk.CTkFont(size=11),
                    fg_color="#c0392b", hover_color="#922b21",
                    command=lambda j=job:
                        messagebox.showerror(
                            f"寄送失敗 — {j.person_name}", j.error))
                btn_err.grid(row=0, column=9, padx=(2, 4))

            if job.status == "skipped":
                chk.configure(state="disabled")

            self._row_widgets.append({
                "job": job, "chk_var": var, "chk": chk,
                "status_lbl": status_lbl, "btn_preview": btn_preview,
            })

        self._update_status_bar()

    def _status_text(self, job: EmailJob) -> str:
        err = (job.error or "").strip()
        # 把可能的多行錯誤訊息壓成一行,並截斷顯示
        err_short = err.replace("\n", " ")[:60]
        m = {
            "pending": "待寄送",
            "sent": "✓ 已寄出",
            "failed": f"✗ {err_short}" if err_short else "✗ 失敗",
            "skipped": f"跳過({err_short})" if err else "跳過",
        }
        return m.get(job.status, job.status)

    def _status_color(self, job: EmailJob) -> str:
        return {
            "pending": "#a0aec0",
            "sent": "#1e8449",
            "failed": "#c0392b",
            "skipped": "#b7950b",
        }.get(job.status, "#a0aec0")

    def _toggle(self, job: EmailJob, var: ctk.BooleanVar):
        job.selected = var.get()
        self._update_status_bar()

    def _select_all(self):
        for rw in self._row_widgets:
            if rw["job"].status != "skipped":
                rw["chk_var"].set(True)
                rw["job"].selected = True
        self._update_status_bar()

    def _select_none(self):
        for rw in self._row_widgets:
            rw["chk_var"].set(False)
            rw["job"].selected = False
        self._update_status_bar()

    def _select_sendable(self):
        for rw in self._row_widgets:
            job = rw["job"]
            ok = job.is_sendable
            rw["chk_var"].set(ok)
            job.selected = ok
        self._update_status_bar()

    def _toggle_zone(self, select: bool):
        """把下拉選到的區的人,一次勾/取消(其他區不動)。

        select=True:把該區所有可寄的人勾起來
        select=False:把該區的人全取消勾選
        skipped 狀態的人不會被影響(本來就無法勾)
        """
        target_zone = self.var_zone_picker.get()
        # "(未分區)" 對應 job.zone == "" 的情況
        match_empty = (target_zone == "(未分區)")
        for rw in self._row_widgets:
            job = rw["job"]
            j_zone = job.zone or ""
            hit = (match_empty and j_zone == "") or (j_zone == target_zone)
            if not hit:
                continue
            if select:
                if job.status != "skipped":
                    rw["chk_var"].set(True)
                    job.selected = True
            else:
                rw["chk_var"].set(False)
                job.selected = False
        self._update_status_bar()

    def _update_status_bar(self):
        selected = sum(1 for j in self.jobs if j.selected and j.is_sendable)
        skipped = sum(1 for j in self.jobs if j.status == "skipped")
        sent = sum(1 for j in self.jobs if j.status == "sent")
        failed = sum(1 for j in self.jobs if j.status == "failed")
        total_bytes = sum(
            j.total_attachment_bytes for j in self.jobs
            if j.selected and j.is_sendable
        )
        mb = total_bytes / (1024 * 1024)

        # 偵測勾選清單裡是否有相同 Email(同診所/同辦公室共用一個信箱
        # 的常見狀況)。提醒使用者:這幾位會把信送到同一個信箱。
        emails = [j.to_email.strip().lower() for j in self.jobs
                  if j.selected and j.is_sendable and j.to_email]
        dup_counts = Counter(emails)
        dup_addrs = [addr for addr, n in dup_counts.items() if n >= 2]

        base = (f"將寄送 {selected} 封(附件合計 {mb:.1f} MB)  |  "
                f"跳過 {skipped}  |  已寄出 {sent}  |  失敗 {failed}")
        if dup_addrs:
            warn = (f"  ⚠ 有 {len(dup_addrs)} 個 Email 被多人共用,"
                    f"會收到多封(請於送出前確認)")
            self.status_lbl.configure(text=base + warn,
                                      text_color="#d35400")
        else:
            self.status_lbl.configure(text=base, text_color="#a0aec0")

    def _preview_job(self, job: EmailJob):
        win = ctk.CTkToplevel(self)
        win.title(f"預覽 / 編輯 — {job.person_name}")
        win.geometry("720x680")
        win.transient(self)

        # ── 主旨(可編輯) ──
        frm = ctk.CTkFrame(win, fg_color="transparent")
        frm.pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkLabel(frm, text="主旨:", width=60,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(side="left")
        subj_var = ctk.StringVar(value=job.subject)
        ctk.CTkEntry(frm, textvariable=subj_var, height=30).pack(
            side="left", fill="x", expand=True, padx=(8, 0))

        # ── 收件者 ──
        frm2 = ctk.CTkFrame(win, fg_color="transparent")
        frm2.pack(fill="x", padx=15, pady=2)
        ctk.CTkLabel(frm2, text="收件者:", width=60,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(side="left")
        ctk.CTkLabel(frm2, text=job.to_email or "(無)",
                     anchor="w").pack(side="left", padx=(8, 0))

        # ── 警告:這個編輯只影響「這位收件人」 ──
        warn = ctk.CTkFrame(win, fg_color="#3d2914", corner_radius=6)
        warn.pack(fill="x", padx=15, pady=(8, 2))
        ctk.CTkLabel(
            warn,
            text=(f"⚠ 修改僅套用至「{job.person_name}」這封信。"
                  f"若要對所有人加共同訊息,請關掉這個視窗,"
                  f"回主程式填寫「6. 補充說明」後重新掃描。"),
            text_color="#f1c40f",
            font=ctk.CTkFont(size=11),
            wraplength=680,
            justify="left",
        ).pack(padx=10, pady=8, anchor="w")

        # ── 內文(可編輯,只影響本人) ──
        body_lbl = ctk.CTkFrame(win, fg_color="transparent")
        body_lbl.pack(fill="x", padx=15, pady=(10, 2))
        ctk.CTkLabel(body_lbl,
                     text=f"內文 ({job.person_name} 專屬,可直接修改):",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(side="left")
        ctk.CTkLabel(body_lbl,
                     text="  ※ 修改後請按下方「儲存修改」",
                     text_color="#a0aec0",
                     font=ctk.CTkFont(size=11)).pack(side="left")

        txt = ctk.CTkTextbox(win, height=260,
                             font=ctk.CTkFont(family="Microsoft JhengHei UI",
                                              size=12),
                             wrap="word")
        txt.pack(fill="both", expand=True, padx=15, pady=(0, 8))
        txt.insert("1.0", job.body)

        # ── 動作按鈕 ──
        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=15, pady=(0, 10))

        def _save_only():
            job.subject = subj_var.get().strip() or job.subject
            job.body = txt.get("1.0", "end-1c")
            self._refresh_rows()
            win.destroy()

        def _reset_default():
            if not messagebox.askyesno(
                "還原預設",
                "確定要丟棄修改、回到自動產生的內文嗎?",
                parent=win,
            ):
                return
            txt.delete("1.0", "end")
            txt.insert("1.0", self._original_bodies.get(id(job), job.body))

        ctk.CTkButton(btn_row, text="💾 儲存修改(僅此人)", width=160, height=32,
                      fg_color="#1e8449", hover_color="#196f3d",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=_save_only).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="↺ 還原", width=70, height=32,
                      fg_color="gray55", hover_color="gray45",
                      command=_reset_default).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="取消", width=70, height=32,
                      fg_color="gray45", hover_color="gray35",
                      command=win.destroy).pack(side="right")

        # ── 附件 ──
        ctk.CTkLabel(win, text=f"附件({len(job.attachments)}):",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(fill="x", padx=15, pady=(6, 2))
        att_box = ctk.CTkTextbox(win, height=90,
                                 font=ctk.CTkFont(family=MONO_FONT, size=11))
        att_box.pack(fill="both", expand=False, padx=15, pady=(0, 15))
        for p in job.attachments:
            att_box.insert("end", f"{p}\n")
        att_box.configure(state="disabled")

    def _on_send_clicked(self):
        # 防重入:寄送中再點按鈕直接忽略
        if self._sending:
            return

        selected_jobs = [j for j in self.jobs if j.selected and j.is_sendable]
        if not selected_jobs:
            messagebox.showinfo("無可寄送項目", "沒有勾選任何可寄送的信件。")
            return

        # 立刻 disable 按鈕(包含 Password Dialog 顯示期間)防止連按
        original_btn_text = "✉ 確認寄送勾選項目"
        self.btn_send.configure(state="disabled", text="準備寄送…")
        self._collect_password_and_start(selected_jobs, original_btn_text)

    def _collect_password_and_start(self, selected_jobs, original_btn_text):
        """跟使用者要 App Password、最終確認、啟動寄送 worker。

        分離出來的目的:讓「按按鈕→disable→中途取消」這個流程
        可以用 try/finally 把按鈕乾淨復原,不會因為早 return 而忘記。
        """
        will_start_worker = False
        try:
            pw_dialog = ctk.CTkInputDialog(
                title="Gmail App Password",
                text=f"即將寄送 {len(selected_jobs)} 封信。\n"
                     f"請輸入 {self.sender_email} 的 App Password:")
            app_password_raw = pw_dialog.get_input()
            if not app_password_raw:
                return
            app_password = _normalize_app_password(app_password_raw)
            if not app_password:
                messagebox.showwarning("未輸入密碼", "已取消寄送。")
                return
            if len(app_password) != 16:
                if not messagebox.askyesno(
                    "密碼長度異常",
                    f"你輸入的密碼長度為 {len(app_password)} 字元,"
                    f"Gmail App Password 標準為 16 字元。\n\n"
                    f"是否仍要嘗試送出?(可能會被 Google 拒絕)",
                ):
                    return

            # 重複信箱再次確認(同一信箱會收到多封)
            dup_counter = Counter(j.to_email.strip().lower()
                                  for j in selected_jobs if j.to_email)
            dup_addrs = [a for a, n in dup_counter.items() if n >= 2]
            dup_warn = ""
            if dup_addrs:
                dup_warn = (
                    f"\n⚠ 注意:有 {len(dup_addrs)} 個信箱被多人共用,"
                    f"會收到多封信:\n"
                    + "\n".join(f"  • {a}" for a in dup_addrs[:5])
                    + ("\n  …" if len(dup_addrs) > 5 else "")
                    + "\n"
                )

            if not messagebox.askyesno(
                "確認寄送",
                f"即將寄送 {len(selected_jobs)} 封 Gmail "
                f"(一封一封循序寄送,每封間隔 "
                f"{SEND_INTERVAL_SECONDS:.1f} 秒)。\n\n"
                f"寄件者:{self.sender_email}\n"
                f"附件合計:"
                f"{sum(j.total_attachment_bytes for j in selected_jobs) / 1024 / 1024:.1f} MB"
                f"{dup_warn}\n"
                f"確認繼續?",
            ):
                return

            # 一切確認後才啟動 worker
            self._sending = True
            will_start_worker = True
            self.btn_send.configure(text="寄送中…")
            threading.Thread(
                target=self._send_worker,
                args=(selected_jobs, app_password),
                daemon=True,
            ).start()
        finally:
            # 中途取消(沒進到 worker)時把按鈕復原
            if not will_start_worker:
                self.btn_send.configure(
                    state="normal", text=original_btn_text)

    def _send_worker(self, selected_jobs: list[EmailJob], app_password: str):
        total = len(selected_jobs)
        auth_error = False
        try:
            for idx, job in enumerate(selected_jobs, 1):
                self.after(0, lambda j=job, i=idx, t=total:
                           self._mark_status(j, "sending", progress=(i, t)))
                try:
                    send_via_gmail_smtp(self.sender_email, app_password, job)
                except SmtpAuthError as e:
                    auth_error = True
                    self.after(0, lambda msg=str(e): messagebox.showerror(
                        "Gmail 認證失敗", msg))
                    break
                except Exception:
                    pass
                finally:
                    self.after(0, lambda j=job: self._mark_status(j, j.status))

                # 一封一封寄:除最後一封外,等一下再送下一封,
                # 避免被 Gmail 視為大量寄送、也讓使用者看到逐封進度。
                if idx < total and not auth_error:
                    time.sleep(SEND_INTERVAL_SECONDS)
        finally:
            # 不論成功/失敗/中斷,務必還原按鈕跟 _sending 旗標
            def _restore():
                self._sending = False
                self.btn_send.configure(
                    state="normal", text="✉ 確認寄送勾選項目")
            self.after(0, _restore)

        if not auth_error:
            sent = sum(1 for j in selected_jobs if j.status == "sent")
            failed = sum(1 for j in selected_jobs if j.status == "failed")
            self.after(0, lambda: messagebox.showinfo(
                "寄送完成",
                f"成功:{sent}\n失敗:{failed}\n總計:{total}"))

    def _mark_status(self, job: EmailJob, display_status: str,
                     progress: tuple[int, int] | None = None):
        for rw in self._row_widgets:
            if rw["job"] is job:
                if display_status == "sending":
                    if progress:
                        i, t = progress
                        rw["status_lbl"].configure(
                            text=f"寄送中… ({i}/{t})",
                            text_color="#a0aec0")
                    else:
                        rw["status_lbl"].configure(text="寄送中…",
                                                    text_color="#a0aec0")
                else:
                    rw["status_lbl"].configure(
                        text=self._status_text(job),
                        text_color=self._status_color(job))
                break
        self._update_status_bar()
