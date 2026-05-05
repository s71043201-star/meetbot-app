"""Gmail 寄送器(獨立應用)
跟核銷文件產生器分開,可隨時啟動寄送,不必等產生流程跑完。
"""
import os
import sys
import customtkinter as ctk
from tkinter import filedialog, messagebox
from datetime import date

from people_db import load_people_db
from email_sender import build_email_jobs, build_body
from email_preview import EmailPreviewWindow


# 全域樣式(同 app.py)
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")
try:
    ctk.ThemeManager.theme["CTkFont"]["family"] = "Microsoft JhengHei UI"
    ctk.ThemeManager.theme["CTkFont"]["size"] = 13
    ctk.ThemeManager.theme["CTkFont"]["weight"] = "normal"
except Exception:
    pass

UI_FONT = "Microsoft JhengHei UI"
MONO_FONT = "Cascadia Mono"


# 偵測執行位置(exe 打包後用 sys.executable,開發時用 __file__)
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))


class EmailSenderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("📧 Gmail 寄送器 — 獨立寄送介面")
        # 預設高度壓低成 760,小螢幕(13"/14" 筆電)也看得到底部按鈕。
        # 不夠用就拉大或捲動主內容區。
        self.geometry("760x760")
        self.minsize(680, 560)
        self.configure(fg_color="#0f1419")
        self._build_ui()

    def _build_ui(self):
        # 重要:先 pack「底部按鈕區」固定在視窗最下,再 pack「可捲動主內容」,
        # 這樣不管螢幕多小、內容多長,「掃描並開啟寄送預覽」按鈕一定看得到。
        footer = ctk.CTkFrame(self, fg_color="#0f1419")
        footer.pack(side="bottom", fill="x", padx=20, pady=(8, 16))

        ctk.CTkButton(
            footer, text="📋 掃描並開啟寄送預覽",
            height=48,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#1e8449", hover_color="#196f3d",
            command=self._on_scan_clicked,
        ).pack(fill="x")

        # 訊息區(成功/錯誤訊息)放在按鈕下方,也固定可見
        self.lbl_msg = ctk.CTkLabel(footer, text="",
                                     text_color="#a0aec0",
                                     font=ctk.CTkFont(size=11),
                                     anchor="w")
        self.lbl_msg.pack(fill="x", pady=(8, 0))

        # 主內容區做成可捲動,內容再多也不擠掉按鈕
        main = ctk.CTkScrollableFrame(self, fg_color="#0f1419")
        main.pack(side="top", fill="both", expand=True, padx=10, pady=(16, 0))

        # ── 頂部 banner ──
        banner = ctk.CTkFrame(main, fg_color="#1a2332",
                              corner_radius=12, border_width=1,
                              border_color="#2c3e50")
        banner.pack(fill="x", pady=(0, 18))
        title_inner = ctk.CTkFrame(banner, fg_color="transparent")
        title_inner.pack(padx=20, pady=14)
        ctk.CTkLabel(title_inner, text="📧  Gmail 寄送器",
                     font=ctk.CTkFont(size=24, weight="bold"),
                     text_color="#3498db").pack(side="left")
        ctk.CTkLabel(title_inner, text="  v34",
                     font=ctk.CTkFont(family=MONO_FONT, size=13),
                     text_color="#52b3e2").pack(side="left", padx=(10, 0))
        ctk.CTkLabel(banner,
                     text="獨立寄送介面 ◆ 可隨時開啟,不需等產生器跑完",
                     font=ctk.CTkFont(size=12),
                     text_color="#a0aec0").pack(pady=(0, 12))

        today = date.today()
        roc_year = today.year - 1911
        # 預設指上個月
        if today.month == 1:
            prev_year, prev_month = roc_year - 1, 12
        else:
            prev_year, prev_month = roc_year, today.month - 1

        # ── 1. 年月 ──
        self._lbl(main, "1. 申報年月")
        row = ctk.CTkFrame(main, fg_color="transparent")
        row.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(row, text="民國年:").pack(side="left")
        self.var_year = ctk.StringVar(value=str(prev_year))
        ctk.CTkEntry(row, textvariable=self.var_year, width=70,
                     height=32).pack(side="left", padx=(8, 18))
        ctk.CTkLabel(row, text="月份:").pack(side="left")
        self.var_month = ctk.StringVar(value=str(prev_month))
        ctk.CTkOptionMenu(row, variable=self.var_month,
                          values=[str(i) for i in range(1, 13)],
                          width=70, height=32).pack(side="left", padx=8)

        # ── 2. 核銷文件根資料夾 ──
        self._lbl(main, "2. 核銷文件根資料夾(內含 N年MM月/ 子資料夾)")
        row2 = ctk.CTkFrame(main, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 12))
        default_output = os.path.join(APP_DIR, "核銷文件")
        self.var_output = ctk.StringVar(value=default_output)
        ctk.CTkEntry(row2, textvariable=self.var_output,
                     height=36).pack(side="left", fill="x", expand=True,
                                     padx=(0, 8))
        ctk.CTkButton(row2, text="選擇資料夾", width=100, height=36,
                      command=self._browse_output).pack(side="right")

        # ── 2.5 區別(可多選) ──
        self._lbl(main, "2.5 區別(勾選要寄哪幾區,點「全選」可一鍵切換)")
        zone_top = ctk.CTkFrame(main, fg_color="transparent")
        zone_top.pack(fill="x", pady=(0, 4))
        self.var_zone_all = ctk.BooleanVar(value=True)
        self.chk_zone_all = ctk.CTkCheckBox(
            zone_top, text="全選", variable=self.var_zone_all,
            command=self._toggle_all_zones,
            font=ctk.CTkFont(size=12, weight="bold"))
        self.chk_zone_all.pack(side="left", padx=(0, 16))
        ctk.CTkButton(zone_top, text="↻ 重新偵測區別", width=130, height=28,
                      fg_color="gray55", hover_color="gray45",
                      command=self._refresh_zone_options).pack(side="left")

        # 各區 checkbox 動態長出來,放在這個 frame 裡
        self.zone_box = ctk.CTkFrame(main, fg_color="#1a2332",
                                      corner_radius=8, border_width=1,
                                      border_color="#2c3e50")
        self.zone_box.pack(fill="x", pady=(4, 12), ipady=4)
        self.zone_vars: dict[str, ctk.BooleanVar] = {}
        self.zone_hint_lbl: ctk.CTkLabel | None = None

        # 年/月/根資料夾變動時自動重新偵測子資料夾
        self.var_year.trace_add("write",
                                 lambda *_a: self._refresh_zone_options())
        self.var_month.trace_add("write",
                                  lambda *_a: self._refresh_zone_options())
        self.var_output.trace_add("write",
                                   lambda *_a: self._refresh_zone_options())
        # 啟動時偵測一次
        self.after(80, self._refresh_zone_options)

        # ── 3. 個資檔 ──
        self._lbl(main, "3. 人員個資 Excel(讀取信箱與連絡資訊)")
        row3 = ctk.CTkFrame(main, fg_color="transparent")
        row3.pack(fill="x", pady=(0, 12))
        # 預設先試最完整的版本
        for cand in ("人員個資+分行_已填代號.xlsx",
                     "人員個資+分行.xlsx",
                     "人員個資.xlsx"):
            cand_path = os.path.join(APP_DIR, cand)
            if os.path.exists(cand_path):
                default_db = cand_path
                break
        else:
            default_db = os.path.join(APP_DIR, "人員個資.xlsx")
        self.var_people_db = ctk.StringVar(value=default_db)
        ctk.CTkEntry(row3, textvariable=self.var_people_db,
                     height=36).pack(side="left", fill="x", expand=True,
                                     padx=(0, 8))
        ctk.CTkButton(row3, text="選擇檔案", width=100, height=36,
                      command=self._browse_people_db).pack(side="right")

        # ── 4. 寄件 Gmail ──
        self._lbl(main, "4. 寄件 Gmail(App Password 於寄送時輸入)")
        row4 = ctk.CTkFrame(main, fg_color="transparent")
        row4.pack(fill="x", pady=(0, 12))
        self.var_sender = ctk.StringVar()
        ctk.CTkEntry(row4, textvariable=self.var_sender,
                     placeholder_text="your-name@gmail.com",
                     height=36).pack(side="left", fill="x", expand=True)

        # ── 5. 範例 PDF Drive 連結 ──
        self._lbl(main, "5. 領據填寫範例 Drive 連結 (選填,填了就不附範本 PDF,改在信中放連結)")
        row5 = ctk.CTkFrame(main, fg_color="transparent")
        row5.pack(fill="x", pady=(0, 12))
        self.var_template_link = ctk.StringVar()
        ctk.CTkEntry(row5, textvariable=self.var_template_link,
                     placeholder_text="https://drive.google.com/file/d/XXX/view?usp=sharing",
                     height=36).pack(side="left", fill="x", expand=True)

        # ── 6. 補充說明 ──
        self._lbl(main, "6. 補充說明 / 更新通知 (選填,會插入每封信的「📢 補充說明」區塊)")
        self.txt_extra = ctk.CTkTextbox(
            main, height=80,
            font=ctk.CTkFont(family=UI_FONT, size=12),
            fg_color="#1a2332", border_width=1, border_color="#2c3e50",
            wrap="word",
        )
        self.txt_extra.pack(fill="x", pady=(0, 8))

        # ── 7. 信件範本預覽(read-only,即時更新) ──
        prev_hdr = ctk.CTkFrame(main, fg_color="transparent")
        prev_hdr.pack(fill="x", pady=(4, 4))
        ctk.CTkLabel(prev_hdr, text="┃", text_color="#3498db",
                     font=ctk.CTkFont(size=18, weight="bold")
                     ).pack(side="left", padx=(0, 4))
        ctk.CTkLabel(prev_hdr,
                     text="信件範本預覽 (制式內容,會自動帶入你的補充說明)",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#dde6ed",
                     anchor="w").pack(side="left")
        ctk.CTkLabel(prev_hdr, text="  唯讀",
                     text_color="#7f8c8d",
                     font=ctk.CTkFont(size=11)).pack(side="left")

        self.txt_preview = ctk.CTkTextbox(
            main, height=200,
            font=ctk.CTkFont(family=UI_FONT, size=11),
            fg_color="#0d1419", border_width=1, border_color="#2c3e50",
            wrap="word",
        )
        self.txt_preview.pack(fill="both", expand=False, pady=(0, 14))

        # 補充說明 / 年月 / 範例連結 變動時即時更新預覽
        self.txt_extra.bind("<KeyRelease>",
                            lambda _e: self._refresh_preview())
        self.var_year.trace_add("write",
                                lambda *_a: self._refresh_preview())
        self.var_month.trace_add("write",
                                  lambda *_a: self._refresh_preview())
        self.var_template_link.trace_add("write",
                                          lambda *_a: self._refresh_preview())
        self.after(50, self._refresh_preview)

        # 「掃描並開啟寄送預覽」按鈕跟訊息區現在放在 footer(視窗底部),
        # 不會因為內容太長被擠出畫面。見 _build_ui 開頭。

    def _lbl(self, parent, text):
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="x", pady=(8, 4))
        ctk.CTkLabel(wrap, text="┃", text_color="#3498db",
                     font=ctk.CTkFont(size=18, weight="bold")
                     ).pack(side="left", padx=(0, 4))
        ctk.CTkLabel(wrap, text=text,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#dde6ed",
                     anchor="w").pack(side="left", fill="x", expand=True)

    def _refresh_preview(self):
        """以範例值即時組出信件內文,讓使用者看到制式內容 + 補充說明合併樣貌。"""
        try:
            year = int(self.var_year.get())
            month = int(self.var_month.get())
        except (ValueError, TypeError):
            year, month = 115, 4

        extra = self.txt_extra.get("1.0", "end").strip()
        template_link = self.var_template_link.get().strip()

        sample_files = ["{姓名}_明細領據.pdf"]
        if not template_link:
            sample_files.append("領據填寫範例.pdf")

        body = build_body(
            person_name="{姓名}",
            role="{職稱}",
            clinic_name="{診所}",
            roc_year=year,
            roc_month=month,
            attachments=sample_files,
            template_drive_link=template_link,
            extra_message=extra,
        )

        self.txt_preview.configure(state="normal")
        self.txt_preview.delete("1.0", "end")
        self.txt_preview.insert("1.0", body)
        self.txt_preview.configure(state="disabled")

    def _browse_output(self):
        path = filedialog.askdirectory(title="選擇核銷文件根資料夾")
        if path:
            self.var_output.set(path)

    def _refresh_zone_options(self):
        """掃描 {根}/{年月}/ 下的子資料夾(中山/北投/士林/課程老師…)
        為每一區建一個 checkbox,讓使用者多選。
        年/月/根資料夾任一變動都會被叫到。
        """
        # 記住現有勾選,讓重新偵測時不會把使用者的選擇丟掉
        prev = {z: v.get() for z, v in self.zone_vars.items()}

        # 清掉舊的 checkbox
        for child in self.zone_box.winfo_children():
            child.destroy()
        self.zone_vars.clear()
        self.zone_hint_lbl = None

        # 嘗試取得月份資料夾
        try:
            year = int(self.var_year.get())
            month = int(self.var_month.get())
        except (ValueError, TypeError):
            self._zone_hint("(請先填入正確年月)")
            return
        root = self.var_output.get().strip()
        month_dir = os.path.join(root, f"{year}年{month:02d}月")
        if not os.path.isdir(month_dir):
            self._zone_hint(f"(找不到 {year}年{month:02d}月 資料夾)")
            return

        try:
            sub = sorted(
                d for d in os.listdir(month_dir)
                if os.path.isdir(os.path.join(month_dir, d))
                and not d.startswith(".")
            )
        except OSError:
            sub = []

        if not sub:
            self._zone_hint(f"({year}年{month:02d}月 內沒有區別子資料夾)")
            return

        # 沒有舊勾選紀錄就預設全勾;有的話沿用,沒記錄到的新區預設勾
        for zone in sub:
            v = ctk.BooleanVar(value=prev.get(zone, True))
            chk = ctk.CTkCheckBox(
                self.zone_box, text=zone, variable=v,
                command=self._on_zone_toggle,
                font=ctk.CTkFont(size=12),
            )
            chk.pack(side="left", padx=12, pady=8)
            self.zone_vars[zone] = v

        self._sync_zone_all_state()

    def _zone_hint(self, text: str):
        """月份資料夾不存在 / 內無子資料夾時,在 zone_box 顯示一行提示。"""
        self.zone_hint_lbl = ctk.CTkLabel(
            self.zone_box, text=text,
            text_color="#a0aec0",
            font=ctk.CTkFont(size=12))
        self.zone_hint_lbl.pack(padx=12, pady=8, anchor="w")
        # 沒有區可選,「全選」也沒意義,維持顯示但不做事
        self.var_zone_all.set(False)

    def _toggle_all_zones(self):
        """『全選』checkbox 點下去,一次套用到所有區。"""
        val = self.var_zone_all.get()
        for v in self.zone_vars.values():
            v.set(val)

    def _on_zone_toggle(self):
        """單一區的 checkbox 變動時,更新「全選」的狀態。"""
        self._sync_zone_all_state()

    def _sync_zone_all_state(self):
        if not self.zone_vars:
            self.var_zone_all.set(False)
            return
        all_on = all(v.get() for v in self.zone_vars.values())
        self.var_zone_all.set(all_on)

    def _browse_people_db(self):
        path = filedialog.askopenfilename(
            title="選擇人員個資 Excel",
            filetypes=[("Excel 檔案", "*.xlsx"), ("所有檔案", "*.*")])
        if path:
            self.var_people_db.set(path)

    def _on_scan_clicked(self):
        sender = self.var_sender.get().strip()
        if not sender:
            messagebox.showwarning("缺少寄件者", "請填入寄件 Gmail。")
            return
        if "@" not in sender:
            messagebox.showwarning("Email 格式錯誤", "寄件 Gmail 格式不對。")
            return

        try:
            year = int(self.var_year.get())
            month = int(self.var_month.get())
        except (ValueError, TypeError):
            messagebox.showerror("錯誤", "年月必須是數字。")
            return

        output = self.var_output.get().strip()
        if not output:
            messagebox.showwarning("缺少根資料夾",
                                    "請選擇核銷文件根資料夾。")
            return

        prefix = f"{year}年{month:02d}月"
        month_dir = os.path.join(output, prefix)
        if not os.path.isdir(month_dir):
            messagebox.showwarning(
                "找不到月份資料夾",
                f"找不到:\n{month_dir}\n\n"
                "請確認年月跟根資料夾正確,且該月已經跑過產生器。")
            return

        # 區別多選:勾的區才掃,沒勾的不掃。沒有任何區可選時(課程老師之類)
        # 直接掃整個月份。
        selected_zones = [z for z, v in self.zone_vars.items() if v.get()]
        if self.zone_vars and not selected_zones:
            messagebox.showwarning(
                "未勾選任何區",
                "請至少勾選一區,或按「全選」一次選全部。")
            return

        receipt_lookup = {}
        db_path = self.var_people_db.get().strip()
        if db_path and os.path.exists(db_path):
            receipt_lookup = load_people_db(db_path)

        # 全部區都勾(等同沒指定),省略 allowed_zones 讓 glob 直接用 month_dir;
        # 部分勾的話傳清單,build_email_jobs 只掃這幾個區的 PDF。
        all_zones_selected = (
            bool(self.zone_vars) and
            all(v.get() for v in self.zone_vars.values())
        )
        zones_arg = None if all_zones_selected else (selected_zones or None)

        scan_label = (f"掃描中: {month_dir}"
                      f"{(' (區別: ' + '、'.join(selected_zones) + ')') if zones_arg else ''}")
        self.lbl_msg.configure(text=scan_label, text_color="#a0aec0")
        self.update_idletasks()

        template_link = self.var_template_link.get().strip()
        extra_message = self.txt_extra.get("1.0", "end").strip()
        jobs = build_email_jobs(month_dir, receipt_lookup, year, month,
                                template_drive_link=template_link,
                                extra_message=extra_message,
                                allowed_zones=zones_arg)
        if not jobs:
            self.lbl_msg.configure(text="(找不到任何合併 PDF)",
                                    text_color="#c0392b")
            zone_hint = (f"\n選擇的區:{'、'.join(selected_zones)}"
                         if zones_arg else "")
            messagebox.showinfo(
                "無可寄送項目",
                f"在 {month_dir} 找不到任何合併 PDF。{zone_hint}\n"
                "預期結構為 *領據/PDF/**/*.pdf。\n"
                "請確認該月已經產生過領據,或調整勾選的區別。")
            return

        sendable = sum(1 for j in jobs if j.status == "pending")
        zone_summary = (f"  |  區別: {'、'.join(selected_zones)}"
                        if zones_arg else "  |  區別: 全部")
        self.lbl_msg.configure(
            text=f"✓ 找到 {len(jobs)} 位人員,可寄送 {sendable} 位{zone_summary}",
            text_color="#1e8449")

        EmailPreviewWindow(self, jobs, sender)


if __name__ == "__main__":
    app = EmailSenderApp()
    app.mainloop()
