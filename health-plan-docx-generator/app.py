"""健康台灣深耕計畫 — Word 核銷文件產生器（桌面 GUI 版）"""

import os
import sys
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox
from datetime import date

from config import PEOPLE_DIVISOR, MIN_PRESCRIPTIONS_DEFAULT, config_source
from reader import read_prescription_report
from excel_writer import (
    read_raw_records,
    generate_prescription_fee_excel,
    generate_execution_fee_excel,
    generate_health_mgmt_excel,
    generate_health_mgmt_excel_per_clinic,
)
from templates.clone_fill import (
    generate_prescription_fee_from_template,
    generate_execution_fee_from_template,
)
from templates.clinic import (
    generate_prescription_fee_doc,
    generate_execution_fee_doc,
    generate_health_mgmt_doc,
)
from templates.executor import (
    generate_treatment_fee_doc,
    generate_executor_patient_list_doc,
    generate_executor_merged_docs,
    generate_doctor_receipts,
    generate_health_mgmt_individual_docs,
    _convert_docx_list_to_pdf,
    merge_doctor_receipt_pdfs,
    merge_health_mgmt_pdfs,
    merge_executor_pdfs,
)
from receipt_reader import load_receipts_from_dir
from people_db import load_people_db, create_template, export_to_db
from email_sender import (
    build_email_jobs,
    send_via_gmail_smtp,
    EmailJob,
    SmtpAuthError,
)
import regions as regions_mod


# 偵測執行位置（exe 打包後用 sys.executable，開發時用 __file__）
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "word_templates")

# 預設模板路徑
DEFAULT_TEMPLATES = {
    "prescription": os.path.join(TEMPLATE_DIR, "處方費_template.docx"),
    "execution": os.path.join(TEMPLATE_DIR, "處方執行費_template.docx"),
    "health_mgmt": os.path.join(TEMPLATE_DIR, "健康管理費_template.docx"),
}

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("健康台灣深耕計畫 — 核銷文件產生器")
        self.geometry("780x720")
        self.minsize(700, 600)

        self._build_ui()

    def _build_ui(self):
        # Scrollable main frame
        main = ctk.CTkScrollableFrame(self)
        main.pack(fill="both", expand=True, padx=20, pady=20)

        # ── Title ──
        ctk.CTkLabel(main, text="核銷文件產生器",
                     font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(0, 5))
        ctk.CTkLabel(main, text="台北市醫師公會 健康台灣深耕計畫",
                     font=ctk.CTkFont(size=13),
                     text_color="gray50").pack(pady=(0, 15))

        # ── 資料來源 ──
        self._section_label(main, "1. 匯入處方紀錄（分開立/執行兩份，以便跨月核銷）")

        # 開立處方紀錄（處方費 + 健康管理費）
        frame_src = ctk.CTkFrame(main, fg_color="transparent")
        frame_src.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(frame_src, text="開立", width=40).pack(side="left")
        self.var_excel = ctk.StringVar()
        ctk.CTkEntry(frame_src, textvariable=self.var_excel,
                     placeholder_text="開立處方 Excel（處方費 + 健康管理費）...",
                     height=36).pack(side="left", fill="x", expand=True,
                                     padx=(0, 8))
        ctk.CTkButton(frame_src, text="選擇檔案", width=100, height=36,
                      command=self._browse_excel).pack(side="right")

        # 執行處方紀錄（處方執行費 + 處方處置費）
        frame_src2 = ctk.CTkFrame(main, fg_color="transparent")
        frame_src2.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(frame_src2, text="執行", width=40).pack(side="left")
        self.var_exec_excel = ctk.StringVar()
        ctk.CTkEntry(frame_src2, textvariable=self.var_exec_excel,
                     placeholder_text="執行處方 Excel（處方執行費 + 處方處置費；留空則用開立檔）...",
                     height=36).pack(side="left", fill="x", expand=True,
                                     padx=(0, 8))
        ctk.CTkButton(frame_src2, text="選擇檔案", width=100, height=36,
                      command=self._browse_exec_excel).pack(side="right")

        # ── 申報設定 ──
        self._section_label(main, "2. 申報設定")
        frame_cfg = ctk.CTkFrame(main, corner_radius=10)
        frame_cfg.pack(fill="x", pady=(0, 10))

        today = date.today()
        roc_year = today.year - 1911

        row1 = ctk.CTkFrame(frame_cfg, fg_color="transparent")
        row1.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(row1, text="申報年度（民國）").pack(side="left")
        self.var_year = ctk.StringVar(value=str(roc_year))
        ctk.CTkEntry(row1, textvariable=self.var_year, width=70,
                     height=32).pack(side="left", padx=(5, 20))

        ctk.CTkLabel(row1, text="申報月份").pack(side="left")
        self.var_month = ctk.StringVar(value=str(today.month))
        month_menu = ctk.CTkOptionMenu(
            row1, values=[str(i) for i in range(1, 13)],
            variable=self.var_month, width=70, height=32)
        month_menu.pack(side="left", padx=(5, 20))

        ctk.CTkLabel(row1, text="分區").pack(side="left")
        self.var_region = ctk.StringVar(value="全部")
        region_menu = ctk.CTkOptionMenu(
            row1, values=["全部"] + list(regions_mod.REGION_NAMES),
            variable=self.var_region, width=90, height=32,
            command=self._on_region_changed)
        region_menu.pack(side="left", padx=5)

        # 第二列：每個分區的最低份數（選「全部」時全部顯示，否則只顯示單一分區）
        row2 = ctk.CTkFrame(frame_cfg, fg_color="transparent")
        row2.pack(fill="x", padx=15, pady=(3, 8))

        self._min_label = ctk.CTkLabel(row2, text="健管費最低份數:")
        self._min_label.pack(side="left")

        # 以 region → StringVar 對應；"全部" scope 不單獨提供欄位（取各區獨立閾值）
        default_min = str(MIN_PRESCRIPTIONS_DEFAULT)
        self.var_min_by_region: dict[str, ctk.StringVar] = {
            r: ctk.StringVar(value=default_min) for r in regions_mod.REGION_NAMES
        }
        # 每個分區對應一個 label + entry 的小元件組，依選擇顯示/隱藏
        self._min_widgets: dict[str, list] = {}
        for r in regions_mod.REGION_NAMES:
            lbl = ctk.CTkLabel(row2, text=f"  {r}")
            entry = ctk.CTkEntry(
                row2, textvariable=self.var_min_by_region[r],
                width=55, height=32)
            lbl.pack(side="left")
            entry.pack(side="left", padx=(3, 8))
            self._min_widgets[r] = [lbl, entry]

        ctk.CTkLabel(
            row2,
            text="(皆需為 4 的倍數;0 代表不過濾、顯示 X/XX)",
            text_color="gray50", font=ctk.CTkFont(size=12)
        ).pack(side="left", padx=12)

        # ── 產出選項 ──
        self._section_label(main, "3. 選擇要產生的文件")
        frame_opts = ctk.CTkFrame(main, corner_radius=10)
        frame_opts.pack(fill="x", pady=(0, 10))

        opts_inner = ctk.CTkFrame(frame_opts, fg_color="transparent")
        opts_inner.pack(padx=15, pady=10)

        self.var_gen_presc = ctk.BooleanVar(value=True)
        self.var_gen_exec = ctk.BooleanVar(value=True)
        self.var_gen_health = ctk.BooleanVar(value=True)
        self.var_gen_treatment = ctk.BooleanVar(value=True)
        self.var_gen_patient = ctk.BooleanVar(value=True)
        self.var_gen_receipt = ctk.BooleanVar(value=True)
        self.var_gen_doctor_receipt = ctk.BooleanVar(value=True)

        checks = [
            ("處方費核銷總表", self.var_gen_presc),
            ("處方執行費核銷總表", self.var_gen_exec),
            ("健康管理費總表", self.var_gen_health),
            ("處方處置費核銷總表", self.var_gen_treatment),
            ("執行人員民眾明細表", self.var_gen_patient),
            ("執行人員領據", self.var_gen_receipt),
            ("醫師處方費/執行費領據", self.var_gen_doctor_receipt),
        ]

        for i, (label, var) in enumerate(checks):
            r, c = divmod(i, 3)
            ctk.CTkCheckBox(opts_inner, text=label, variable=var,
                            font=ctk.CTkFont(size=13)).grid(
                                row=r, column=c, padx=10, pady=4, sticky="w")

        # ── 人員個資檔 ──
        self._section_label(main, "4. 人員個資檔（選填，新增/修改人員資料）")
        frame_db = ctk.CTkFrame(main, fg_color="transparent")
        frame_db.pack(fill="x", pady=(0, 4))

        default_db = os.path.join(APP_DIR, "人員個資.xlsx")
        self.var_people_db = ctk.StringVar(value=default_db)
        ctk.CTkEntry(frame_db, textvariable=self.var_people_db,
                     height=36).pack(side="left", fill="x", expand=True,
                                     padx=(0, 8))
        ctk.CTkButton(frame_db, text="選擇檔案", width=90, height=36,
                      command=self._browse_people_db).pack(side="right")

        frame_db2 = ctk.CTkFrame(main, fg_color="transparent")
        frame_db2.pack(fill="x", pady=(0, 10))
        ctk.CTkButton(frame_db2, text="建立空白範本", width=110, height=30,
                      fg_color="gray60", hover_color="gray50",
                      command=self._create_people_db_template).pack(side="left")
        ctk.CTkButton(frame_db2, text="開啟編輯", width=90, height=30,
                      fg_color="gray60", hover_color="gray50",
                      command=self._open_people_db).pack(side="left", padx=(8, 0))
        ctk.CTkButton(frame_db2, text="從舊領據匯入", width=110, height=30,
                      fg_color="steelblue", hover_color="steelblue4",
                      command=self._import_from_receipts).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(frame_db2,
                     text="  每人一行填寫：姓名、身分證、地址、電話、銀行資訊",
                     text_color="gray50", font=ctk.CTkFont(size=12)).pack(
                         side="left", padx=8)

        # ── 診所分區名單 ──
        self._section_label(main, "5. 診所分區名單（Excel 三分頁：北投/士林/中山）")
        frame_rg = ctk.CTkFrame(main, fg_color="transparent")
        frame_rg.pack(fill="x", pady=(0, 4))

        default_rg = os.path.join(APP_DIR, "診所分區.xlsx")
        self.var_regions_db = ctk.StringVar(value=default_rg)
        ctk.CTkEntry(frame_rg, textvariable=self.var_regions_db,
                     height=36).pack(side="left", fill="x", expand=True,
                                     padx=(0, 8))
        ctk.CTkButton(frame_rg, text="選擇檔案", width=90, height=36,
                      command=self._browse_regions).pack(side="right")

        frame_rg2 = ctk.CTkFrame(main, fg_color="transparent")
        frame_rg2.pack(fill="x", pady=(0, 10))
        ctk.CTkButton(frame_rg2, text="建立空白範本", width=110, height=30,
                      fg_color="gray60", hover_color="gray50",
                      command=self._create_regions_template).pack(side="left")
        ctk.CTkButton(frame_rg2, text="開啟編輯", width=90, height=30,
                      fg_color="gray60", hover_color="gray50",
                      command=self._open_regions).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(frame_rg2,
                     text="  每分頁 A 欄列出該區診所名稱;新增診所直接新增一列即可",
                     text_color="gray50", font=ctk.CTkFont(size=12)).pack(
                         side="left", padx=8)

        # ── 輸出目錄 ──
        self._section_label(main, "6. 輸出位置")
        frame_out = ctk.CTkFrame(main, fg_color="transparent")
        frame_out.pack(fill="x", pady=(0, 10))

        self.var_output = ctk.StringVar(
            value=os.path.join(APP_DIR, "核銷文件"))
        ctk.CTkEntry(frame_out, textvariable=self.var_output,
                     height=36).pack(side="left", fill="x", expand=True,
                                     padx=(0, 8))
        ctk.CTkButton(frame_out, text="選擇資料夾", width=100, height=36,
                      command=self._browse_output).pack(side="right")

        # ── Gmail 寄送設定 ──
        self._section_label(main, "7. Gmail 寄送設定（選填，產生後可批次寄送）")
        frame_mail = ctk.CTkFrame(main, fg_color="transparent")
        frame_mail.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(frame_mail, text="寄件 Gmail").pack(side="left")
        self.var_sender_email = ctk.StringVar()
        ctk.CTkEntry(frame_mail, textvariable=self.var_sender_email,
                     placeholder_text="your-name@gmail.com",
                     height=36).pack(side="left", fill="x", expand=True,
                                     padx=(8, 8))
        ctk.CTkLabel(frame_mail,
                     text="App Password 於寄送時輸入",
                     text_color="gray50",
                     font=ctk.CTkFont(size=11)).pack(side="right")

        # ── 產生按鈕 ──
        self.btn_generate = ctk.CTkButton(
            main, text="產 生 文 件", height=48,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self._on_generate)
        self.btn_generate.pack(pady=(15, 8), fill="x")

        # 寄送按鈕（可直接用既有月份資料夾寄，不必重跑產生）
        self.btn_send_email = ctk.CTkButton(
            main, text="📧 預覽並寄送 Gmail", height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#1e8449", hover_color="#196f3d",
            command=self._on_open_email_preview)
        self.btn_send_email.pack(pady=(0, 15), fill="x")

        # 產生後保存的狀態（供寄送使用）
        self._last_month_dir: str | None = None
        self._last_receipt_lookup: dict = {}
        self._last_year: int | None = None
        self._last_month: int | None = None

        # ── Progress ──
        self.progress = ctk.CTkProgressBar(main)
        self.progress.pack(fill="x", pady=(0, 5))
        self.progress.set(0)

        # ── 日誌 ──
        self.log = ctk.CTkTextbox(main, height=150,
                                  font=ctk.CTkFont(family="Consolas", size=11))
        self.log.pack(fill="both", expand=True)

    def _section_label(self, parent, text):
        ctk.CTkLabel(parent, text=text,
                     font=ctk.CTkFont(size=14, weight="bold"),
                     anchor="w").pack(fill="x", pady=(10, 4))

    def _browse_excel(self):
        path = filedialog.askopenfilename(
            title="選擇開立處方紀錄 Excel",
            filetypes=[("Excel 檔案", "*.xlsx"), ("所有檔案", "*.*")])
        if path:
            self.var_excel.set(path)

    def _browse_exec_excel(self):
        path = filedialog.askopenfilename(
            title="選擇執行處方紀錄 Excel",
            filetypes=[("Excel 檔案", "*.xlsx"), ("所有檔案", "*.*")])
        if path:
            self.var_exec_excel.set(path)

    def _browse_people_db(self):
        path = filedialog.askopenfilename(
            title="選擇人員個資 Excel",
            filetypes=[("Excel 檔案", "*.xlsx"), ("所有檔案", "*.*")])
        if path:
            self.var_people_db.set(path)

    def _create_people_db_template(self):
        path = self.var_people_db.get().strip()
        if not path:
            path = os.path.join(os.path.expanduser("~"), "Desktop", "人員個資.xlsx")
        if os.path.exists(path):
            if not messagebox.askyesno("確認", f"檔案已存在，要覆蓋嗎？\n{path}"):
                return
        create_template(path)
        self.var_people_db.set(path)
        os.startfile(path)

    def _import_from_receipts(self):
        """從舊領據資料夾讀取個資，寫入人員個資 Excel"""
        receipts_dir = filedialog.askdirectory(title="選擇舊領據資料夾")
        if not receipts_dir:
            return
        db_path = self.var_people_db.get().strip()
        if not db_path:
            db_path = os.path.join(APP_DIR, "人員個資.xlsx")
            self.var_people_db.set(db_path)

        def _do_import():
            try:
                self.after(0, lambda: self._log("\n── 從舊領據匯入 ──"))

                def on_progress(msg):
                    self.after(0, lambda m=msg: self._log(m))

                lookup = load_receipts_from_dir(receipts_dir,
                                                progress_cb=on_progress)
                if not lookup:
                    self.after(0, lambda: messagebox.showwarning(
                        "找不到資料", "資料夾內沒有找到領據檔案"))
                    return
                count = export_to_db(lookup, db_path)
                self.after(0, lambda: self._log(
                    f"\n完成！共 {count} 筆人員資料已存入:\n{db_path}"))
                self.after(0, lambda: messagebox.showinfo(
                    "匯入完成",
                    f"已將 {count} 筆人員資料存入個資檔\n\n{db_path}"))
                self.after(0, lambda: os.startfile(db_path))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("錯誤", str(e)))

        threading.Thread(target=_do_import, daemon=True).start()

    def _open_people_db(self):
        path = self.var_people_db.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning("找不到檔案", "請先選擇或建立人員個資檔")
            return
        os.startfile(path)

    def _docx_to_pdf(self, docx_path: str):
        """將 Word 檔轉成同目錄的 PDF（需要 Word 已安裝）

        用 DispatchEx 建立獨立 Word process，避免與先前 instance 衝突造成
        'Word.Application.Visible can not be set' 錯誤。
        """
        try:
            import win32com.client
            pdf_path = docx_path.replace(".docx", ".pdf")
            word = win32com.client.DispatchEx("Word.Application")
            # Visible / DisplayAlerts 設失敗不致命，包 try/except
            try:
                word.Visible = False
            except Exception:
                pass
            try:
                word.DisplayAlerts = 0
            except Exception:
                pass
            try:
                doc = word.Documents.Open(os.path.abspath(docx_path))
                doc.SaveAs(os.path.abspath(pdf_path), FileFormat=17)
                doc.Close(SaveChanges=0)
            finally:
                try:
                    word.Quit()
                except Exception:
                    pass
        except Exception:
            pass

    def _browse_output(self):
        path = filedialog.askdirectory(title="選擇輸出目錄")
        if path:
            self.var_output.set(path)

    # ── 分區相關 ──
    def _on_region_changed(self, *_):
        """依目前分區選擇，顯示/隱藏對應的最低份數欄位。"""
        choice = self.var_region.get()
        for r, widgets in self._min_widgets.items():
            show = (choice == "全部" or choice == r)
            for w in widgets:
                if show:
                    w.pack(side="left", padx=(3, 8) if isinstance(w, ctk.CTkEntry) else 0)
                else:
                    w.pack_forget()

    def _browse_regions(self):
        path = filedialog.askopenfilename(
            title="選擇診所分區 Excel",
            filetypes=[("Excel 檔案", "*.xlsx"), ("所有檔案", "*.*")])
        if path:
            self.var_regions_db.set(path)

    def _create_regions_template(self):
        path = self.var_regions_db.get().strip()
        if not path:
            path = os.path.join(APP_DIR, "診所分區.xlsx")
        if os.path.exists(path):
            if not messagebox.askyesno("確認", f"檔案已存在，要覆蓋嗎？\n{path}"):
                return
        regions_mod.create_template(path)
        self.var_regions_db.set(path)
        os.startfile(path)

    def _open_regions(self):
        path = self.var_regions_db.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning(
                "找不到檔案",
                "請先選擇或建立診所分區檔\n(點「建立空白範本」可自動建立)")
            return
        os.startfile(path)

    def _region_thresholds(self) -> dict[str, int]:
        """回傳 {region: 最低份數}。驗證失敗時丟出 ValueError。"""
        result: dict[str, int] = {}
        for r, var in self.var_min_by_region.items():
            raw = var.get().strip() or "0"
            try:
                v = int(raw)
            except (ValueError, TypeError):
                raise ValueError(
                    f"{r} 份數必須是數字(輸入了 {raw!r})")
            if v < 0:
                raise ValueError(f"{r} 份數不可為負")
            if v % PEOPLE_DIVISOR != 0:
                raise ValueError(
                    f"{r} 份數必須是 {PEOPLE_DIVISOR} 的倍數(對應人數需為整數)")
            result[r] = v
        return result

    def _log(self, text):
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def _log_incomplete_recipients(self, data, receipt_lookup):
        """掃描所有要產領據的人，列出個資不完整的（缺欄位需手動補齊）"""
        REQUIRED_FIELDS = [
            ("id_number",      "身分證字號"),
            ("address",        "戶籍地址"),
            ("phone",          "聯絡電話"),
            ("account_name",   "戶名"),
            ("bank_branch",    "銀行及分行"),
            ("bank_code",      "銀行代碼"),
            ("account_number", "帳號"),
        ]

        # 收集所有要產領據的人 (name, role)
        targets = []
        seen = set()

        for d in data.doctors:
            if d.prescription_fee > 0 or d.execution_fee > 0:
                if d.doctor_name not in seen:
                    targets.append((d.doctor_name, "醫師"))
                    seen.add(d.doctor_name)
        for hm in data.health_mgmts:
            if hm.is_qualified:
                person = hm.clinic_person or hm.medical_institution
                if person and person not in seen:
                    targets.append((person, "健管費"))
                    seen.add(person)
        for ex in data.executors:
            if ex.receipt and ex.receipt.amount > 0:
                if ex.executor_name not in seen:
                    targets.append((ex.executor_name, "處置費"))
                    seen.add(ex.executor_name)

        # 檢查每人個資
        missing_report = []
        for name, role in targets:
            info = receipt_lookup.get(name) if receipt_lookup else None
            if info is None:
                missing_report.append((name, role, ["所有個資（個資檔查無此人）"]))
                continue
            missing = []
            for fld, label in REQUIRED_FIELDS:
                val = getattr(info, fld, None)
                if not val or not str(val).strip():
                    missing.append(label)
            if missing:
                missing_report.append((name, role, missing))

        if not missing_report:
            self._log("\n========== 個資檢查 ==========")
            self._log("✓ 所有領據對應的人員個資完整")
            return

        self._log("\n========== 個資不完整需手動補齊 ==========")
        self._log(f"以下 {len(missing_report)} 人領據需手動補欄位：")
        for name, role, fields in missing_report:
            self._log(f"  • [{role}] {name} → 缺：{', '.join(fields)}")
        self._log("=" * 36)

    def _on_generate(self):
        excel = self.var_excel.get().strip()
        if not excel or not os.path.exists(excel):
            messagebox.showerror("錯誤", "請選擇有效的 Excel 檔案")
            return

        # 驗證各分區健管費最低份數
        try:
            self._region_thresholds_cache = self._region_thresholds()
        except ValueError as e:
            messagebox.showerror("錯誤", str(e))
            return

        self.btn_generate.configure(state="disabled", text="產生中...")
        self.log.delete("1.0", "end")
        self.progress.set(0)
        threading.Thread(target=self._generate_worker, daemon=True).start()

    def _generate_worker(self):
        try:
            self._do_generate()
        except Exception as e:
            self.after(0, lambda: self._log(f"\n錯誤：{e}"))
            self.after(0, lambda: messagebox.showerror("錯誤", str(e)))
        finally:
            self.after(0, lambda: self.btn_generate.configure(
                state="normal", text="產 生 文 件"))

    # ──────────────────────────────────────────────────────
    # 依分區過濾資料
    # ──────────────────────────────────────────────────────
    def _filter_data(self, data, allowed_clinics: set[str]):
        """回傳只保留 medical_institution 在 allowed_clinics 裡的新 AllData。
        executors 不分區（處方處置費跨區共用）。
        """
        from models import AllData
        new_doctors = [d for d in data.doctors
                       if d.medical_institution in allowed_clinics]
        new_hms = [hm for hm in data.health_mgmts
                   if hm.medical_institution in allowed_clinics]
        return AllData(
            report_year=data.report_year,
            report_month=data.report_month,
            doctors=new_doctors,
            health_mgmts=new_hms,
            executors=data.executors,
            min_prescriptions=data.min_prescriptions,
        )

    def _filter_raw_records(self, raw_records, allowed_clinics: set[str]):
        """過濾 raw_records 只留該區診所的列（COL_CLINIC = 7）"""
        return [r for r in raw_records
                if len(r) > 7 and str(r[7] or "") in allowed_clinics]

    # ──────────────────────────────────────────────────────
    # 對單一 scope 產出一組文件
    # ──────────────────────────────────────────────────────
    def _produce_for_scope(
        self,
        scope_label: str,
        data,
        raw_records_issuance,
        raw_records_execution,
        month_dir: str,
        prefix: str,
        min_presc: int,
        receipt_lookup: dict,
        produce_executor: bool,
        step_cb,
    ):
        """在 `month_dir` 下產生一組文件（可能是全部 / 北投 / 士林 / ...）。
        produce_executor：是否產處方處置費相關文件（通常只在全部或第一個 scope 執行一次）。
        回傳 (all_pending_docx, health_merge_info, executor_merge_info, doctor_merge_info)
        """
        os.makedirs(month_dir, exist_ok=True)

        # 子資料夾工具
        def subdir(name):
            d = os.path.join(month_dir, name)
            os.makedirs(d, exist_ok=True)
            return d

        OTHER_DIR = "其他內容"
        def agg_subdir(name):
            """彙整檔資料夾 — 統一放在 其他內容/ 下"""
            d = os.path.join(month_dir, OTHER_DIR, name)
            os.makedirs(d, exist_ok=True)
            return d

        COMBINED_DIR_NAME = "處方費、處方執行費總表明細表合併檔與Excel"
        HEALTH_COMBINED_DIR = "健康管理費合併總表與個人excel"
        TREATMENT_COMBINED_DIR = "處方處置費合併總表word"

        # 產生 Excel 統計檔（每個 scope 都有自己的總表）
        # 處方費 → 開立；執行費 → 執行；健管費 → 開立
        presc_dir = agg_subdir(COMBINED_DIR_NAME)
        try:
            generate_prescription_fee_excel(raw_records_issuance, prefix, presc_dir)
            generate_execution_fee_excel(raw_records_execution, prefix, presc_dir)
        except Exception:
            pass
        hm_dir = agg_subdir(HEALTH_COMBINED_DIR)
        try:
            generate_health_mgmt_excel(raw_records_issuance, prefix, hm_dir)
        except Exception:
            pass
        self.after(0, lambda s=scope_label: self._log(f"[{s}] Excel 統計檔"))

        all_pending_docx: list[str] = []
        health_merge_info = None
        executor_merge_info = None
        doctor_merge_info = None

        if self.var_gen_presc.get() and data.doctors:
            d = agg_subdir(COMBINED_DIR_NAME)
            path = os.path.join(
                d, f"健康台灣深耕計畫_處方費-總表-{prefix}.docx")
            tmpl = DEFAULT_TEMPLATES["prescription"]
            if os.path.exists(tmpl):
                generate_prescription_fee_from_template(tmpl, data, path)
            else:
                generate_prescription_fee_doc(data, path)
            all_pending_docx.append(os.path.abspath(path))
            self.after(0, lambda s=scope_label: self._log(f"[{s}] 處方費核銷總表"))
            step_cb()

        if self.var_gen_exec.get() and data.doctors:
            d = agg_subdir(COMBINED_DIR_NAME)
            path = os.path.join(
                d, f"健康台灣深耕計畫_處方執行費核銷總表-{prefix}.docx")
            tmpl = DEFAULT_TEMPLATES["execution"]
            if os.path.exists(tmpl):
                generate_execution_fee_from_template(tmpl, data, path)
            else:
                generate_execution_fee_doc(data, path)
            all_pending_docx.append(os.path.abspath(path))
            self.after(0, lambda s=scope_label: self._log(f"[{s}] 處方執行費核銷總表"))
            step_cb()

        if self.var_gen_health.get() and data.health_mgmts:
            d = agg_subdir(HEALTH_COMBINED_DIR)
            path = os.path.join(
                d, f"健康台灣深耕計畫_健康管理費總表-{prefix}.docx")
            generate_health_mgmt_doc(data, path, min_prescriptions=min_presc)
            all_pending_docx.append(os.path.abspath(path))

            per_clinic_excel_dir = os.path.join(d, "個別Excel")
            os.makedirs(per_clinic_excel_dir, exist_ok=True)
            clinic_to_person_map = {
                hm.medical_institution: (hm.clinic_person or hm.medical_institution)
                for hm in data.health_mgmts
            }
            try:
                xlsx_paths = generate_health_mgmt_excel_per_clinic(
                    raw_records_issuance, prefix, per_clinic_excel_dir,
                    clinic_to_person=clinic_to_person_map,
                )
            except Exception:
                xlsx_paths = []

            hm_result = generate_health_mgmt_individual_docs(
                data, month_dir,
                receipt_lookup=receipt_lookup, also_pdf=False,
            )
            if hm_result:
                hm_docx_info, hm_receipt_dir = hm_result
                health_merge_info = (hm_docx_info, hm_receipt_dir)
                for _, dd, r in hm_docx_info:
                    all_pending_docx.extend([dd, r])

            hm_count = sum(1 for hm in data.health_mgmts if hm.is_qualified)
            self.after(0, lambda s=scope_label, c=hm_count, x=len(xlsx_paths):
                       self._log(f"[{s}] 健康管理費 ({c} 間診所, 個別Excel×{x})"))
            step_cb()

        if produce_executor and self.var_gen_treatment.get() and data.executors:
            d = agg_subdir(TREATMENT_COMBINED_DIR)
            path = os.path.join(
                d, f"健康台灣深耕計畫_處方處置費核銷總表-{prefix}.docx")
            generate_treatment_fee_doc(data, path)
            self.after(0, lambda s=scope_label: self._log(f"[{s}] 處方處置費核銷總表"))
            step_cb()

        if produce_executor and self.var_gen_patient.get() and data.executors:
            d = agg_subdir(TREATMENT_COMBINED_DIR)
            path = os.path.join(
                d, f"健康台灣深耕計畫_執行人員民眾明細表-{prefix}.docx")
            generate_executor_patient_list_doc(data, path)
            self.after(0, lambda s=scope_label: self._log(f"[{s}] 執行人員民眾明細表"))
            step_cb()

        if produce_executor and self.var_gen_receipt.get() and data.executors:
            ex_result = generate_executor_merged_docs(
                data, month_dir, also_pdf=False,
                receipt_lookup=receipt_lookup)
            if ex_result:
                ex_docx_info, ex_receipt_dir = ex_result
                executor_merge_info = (ex_docx_info, ex_receipt_dir)
                for _, _, dd, r in ex_docx_info:
                    all_pending_docx.extend([dd, r])
            count = sum(1 for ex in data.executors
                        if ex.receipt and ex.receipt.amount > 0)
            self.after(0, lambda s=scope_label, c=count:
                       self._log(f"[{s}] 處方處置費 ({c} 人)"))
            step_cb()

        if self.var_gen_doctor_receipt.get() and data.doctors:
            dr_info = generate_doctor_receipts(
                data, month_dir,
                receipt_lookup=receipt_lookup,
                also_pdf=False)
            if dr_info:
                doctor_merge_info = dr_info
                # 領據是 處方費/執行費 共用，去重避免重複加入
                seen = set()
                for _, _, dd, r, _ in dr_info:
                    for path in (dd, r):
                        if path and path not in seen:
                            all_pending_docx.append(path)
                            seen.add(path)
            count = sum(1 for doc in data.doctors
                        if doc.prescription_fee > 0 or doc.execution_fee > 0)
            self.after(0, lambda s=scope_label, c=count:
                       self._log(f"[{s}] 醫師處方費/處方執行費 ({c} 位)"))
            step_cb()

        return all_pending_docx, health_merge_info, executor_merge_info, doctor_merge_info

    def _do_generate(self):
        issuance_excel = self.var_excel.get().strip()
        execution_excel = self.var_exec_excel.get().strip()
        if not execution_excel:
            execution_excel = issuance_excel  # 單檔相容
        year = int(self.var_year.get())
        month = int(self.var_month.get())
        region_choice = self.var_region.get()
        region_thresholds = getattr(
            self, "_region_thresholds_cache", None) or self._region_thresholds()
        output = self.var_output.get().strip()

        os.makedirs(output, exist_ok=True)

        self.after(0, lambda: self._log(f"設定檔來源: {config_source()}"))
        self.after(0, lambda: self._log("讀取 Excel 中..."))
        self.after(0, lambda p=issuance_excel: self._log(f"  開立: {os.path.basename(p)}"))
        if execution_excel != issuance_excel:
            self.after(0, lambda p=execution_excel:
                       self._log(f"  執行: {os.path.basename(p)}"))
        else:
            self.after(0, lambda: self._log("  執行: (沿用開立檔)"))
        self.after(0, lambda: self.progress.set(0.05))

        # 讀取總資料（read_prescription_report 只用一次,分區時再 filter）
        # min_prescriptions 先傳任一閾值,實際會在每個 scope 重算
        any_threshold = next(
            (v for v in region_thresholds.values() if v > 0), 0)
        data = read_prescription_report(
            issuance_excel,
            execution_path=execution_excel,
            report_year=year, report_month=month,
            min_prescriptions=any_threshold,
        )
        # 兩組 raw records：處方費/健管費 用開立、執行費用執行
        raw_records_issuance = read_raw_records(issuance_excel)
        if execution_excel != issuance_excel:
            raw_records_execution = read_raw_records(execution_excel)
        else:
            raw_records_execution = raw_records_issuance
        # 預設 raw_records 變數供後面程式相容使用（處方費/健管費）
        raw_records = raw_records_issuance

        self.after(0, lambda: self._log(
            f"  醫師: {len(data.doctors)} 位 | "
            f"診所: {len(data.health_mgmts)} 間 | "
            f"執行人員: {len(data.executors)} 位\n"
        ))

        # 人員個資
        receipt_lookup = {}
        db_path = self.var_people_db.get().strip()
        if db_path and os.path.exists(db_path):
            self.after(0, lambda: self._log("讀取人員個資檔..."))
            receipt_lookup = load_people_db(db_path)

        # 診所名 → 人名（用於健管費 clinic_person 修正）
        clinic_to_person = {
            info.clinic_name: person_name
            for person_name, info in receipt_lookup.items()
            if info.role == "診所行政人員" and info.clinic_name
        }

        def _match_clinic(institution):
            if institution in clinic_to_person:
                return clinic_to_person[institution]
            for key, person in clinic_to_person.items():
                if key in institution or institution in key:
                    return person
            if institution:
                best_person = None
                best_len = 0
                for key, person in clinic_to_person.items():
                    if not key:
                        continue
                    prefix_len = 0
                    for a, b in zip(institution, key):
                        if a == b:
                            prefix_len += 1
                        else:
                            break
                    if prefix_len >= 3 and prefix_len > best_len:
                        best_len = prefix_len
                        best_person = person
                if best_person:
                    return best_person
            return None

        for hm in data.health_mgmts:
            person = _match_clinic(hm.medical_institution)
            if person:
                hm.clinic_person = person

        # ── 讀分區名單 ──
        regions_path = self.var_regions_db.get().strip()
        regions_map = regions_mod.load_regions(regions_path)
        if not regions_map or not any(regions_map.values()):
            self.after(0, lambda: self._log(
                "⚠ 無分區名單(檔案不存在或空白),全部診所會歸為「其他」"))

        # 把所有診所依分區分類
        all_clinics: set[str] = set()
        for d in data.doctors:
            all_clinics.add(d.medical_institution)
        for hm in data.health_mgmts:
            all_clinics.add(hm.medical_institution)

        clinic_region: dict[str, str] = {}
        region_to_clinics: dict[str, set[str]] = {
            r: set() for r in regions_mod.REGION_NAMES}
        region_to_clinics["其他"] = set()
        for c in all_clinics:
            r = regions_mod.find_region(c, regions_map) or "其他"
            clinic_region[c] = r
            region_to_clinics.setdefault(r, set()).add(c)

        unclassified = region_to_clinics.get("其他", set())
        if unclassified:
            self.after(0, lambda n=len(unclassified), cs=sorted(unclassified):
                       self._log(
                f"{n} 間診所不在任何分區名單,會放到「其他/」資料夾:\n  - "
                + "\n  - ".join(cs)))

        diag_lines = [
            f"  {r}: {len(region_to_clinics.get(r, set()))} 間"
            for r in regions_mod.REGION_NAMES
        ]
        self.after(0, lambda dl="\n".join(diag_lines):
                   self._log("分區比對結果:\n" + dl))

        # ── 組 scopes ──
        prefix = f"{year}年{month:02d}月"
        month_dir_root = os.path.join(output, prefix)
        os.makedirs(month_dir_root, exist_ok=True)

        scopes: list[tuple[str, set[str], int, str]] = []
        # (scope_label, allowed_clinics, min_presc_for_scope, month_dir)
        if region_choice == "全部":
            # 全部 scope：所有診所，閾值取「最常用」（取最大）
            all_min = max(region_thresholds.values()) if region_thresholds else 0
            scopes.append(
                ("全部", all_clinics,
                 all_min,
                 os.path.join(month_dir_root, "全部")))
            # 再加上每個有診所的分區
            for r in regions_mod.REGION_NAMES:
                clinics = region_to_clinics.get(r, set())
                if clinics:
                    scopes.append((
                        r, clinics,
                        region_thresholds.get(r, 0),
                        os.path.join(month_dir_root, r)))
            if unclassified:
                scopes.append((
                    "其他", unclassified, 0,
                    os.path.join(month_dir_root, "其他")))
        else:
            clinics = region_to_clinics.get(region_choice, set())
            if not clinics:
                self.after(0, lambda rc=region_choice: self._log(
                    f"⚠ 選擇的分區「{rc}」沒有任何診所"))
            scopes.append((
                region_choice, clinics,
                region_thresholds.get(region_choice, 0),
                os.path.join(month_dir_root, region_choice)))

        self.after(0, lambda: self._log(f"\n產生範圍：{len(scopes)} 個 scope"))

        # ── 進度 ──
        per_scope_steps = sum([
            self.var_gen_presc.get(),
            self.var_gen_exec.get(),
            self.var_gen_health.get(),
            self.var_gen_doctor_receipt.get(),
        ])
        executor_steps = sum([
            self.var_gen_treatment.get(),
            self.var_gen_patient.get(),
            self.var_gen_receipt.get(),
        ])
        total_steps = per_scope_steps * len(scopes) + executor_steps
        if total_steps == 0:
            total_steps = 1

        steps_done = 0

        def step_cb():
            nonlocal steps_done
            steps_done += 1
            self.after(0, lambda: self.progress.set(
                0.1 + 0.85 * steps_done / total_steps))

        # ── 逐 scope 產出 ──
        all_pending_docx: list[str] = []
        merge_bundles: list[tuple] = []  # (health, executor, doctor)

        for i, (scope_label, allowed, threshold, month_dir) in enumerate(scopes):
            produce_exec = (i == 0)  # 處方處置費只在第一個 scope 產
            # 過濾資料
            if scope_label == "全部":
                data_scope = data
                raw_scope_issuance = raw_records_issuance
                raw_scope_execution = raw_records_execution
            else:
                data_scope = self._filter_data(data, allowed)
                raw_scope_issuance = self._filter_raw_records(
                    raw_records_issuance, allowed)
                raw_scope_execution = self._filter_raw_records(
                    raw_records_execution, allowed)

            # 該 scope 的 min_prescriptions 要重算 is_qualified
            for hm in data_scope.health_mgmts:
                hm.is_qualified = (
                    threshold == 0
                    or hm.prescription_count >= threshold)
            data_scope.min_prescriptions = threshold

            has_data = bool(data_scope.doctors) or bool(data_scope.health_mgmts) \
                or (produce_exec and data_scope.executors)
            if not has_data:
                self.after(0, lambda s=scope_label: self._log(
                    f"[{s}] 無資料，略過"))
                continue

            pending, hi, ei, di = self._produce_for_scope(
                scope_label=scope_label,
                data=data_scope,
                raw_records_issuance=raw_scope_issuance,
                raw_records_execution=raw_scope_execution,
                month_dir=month_dir,
                prefix=prefix,
                min_presc=threshold,
                receipt_lookup=receipt_lookup,
                produce_executor=produce_exec,
                step_cb=step_cb,
            )
            all_pending_docx.extend(pending)
            merge_bundles.append((hi, ei, di))

        # ── 一次批次 Word → PDF ──
        if all_pending_docx:
            total_pdf = len(all_pending_docx)
            self.after(0, lambda: self._log(
                f"\n批次轉換 {total_pdf} 份 Word → PDF（共用一個 Word 程序）..."))

            def _pdf_progress(done, total, name):
                if done % 10 == 0 or done == total:
                    self.after(0, lambda d=done, t=total, n=name:
                               self._log(f"  [{d}/{t}] {n}"))
            _convert_docx_list_to_pdf(all_pending_docx, progress_cb=_pdf_progress)
            self.after(0, lambda: self._log(
                f"[OK] {total_pdf} 份 PDF 轉換完成"))

        # ── 合併每人的「明細 + 領據」PDF（不含總表）──
        for health_merge_info, executor_merge_info, doctor_merge_info in merge_bundles:
            if health_merge_info:
                merge_health_mgmt_pdfs(*health_merge_info)
            if executor_merge_info:
                merge_executor_pdfs(*executor_merge_info)
            if doctor_merge_info:
                merge_doctor_receipt_pdfs(doctor_merge_info)

        # ── 列出個資不完整的人員（領據缺欄位的）──
        self._log_incomplete_recipients(data, receipt_lookup)

        # 記住本次輸出根（Email 掃描用 month_dir_root，glob 會吸收子分區）
        month_dir = month_dir_root

        self.after(0, lambda: self.progress.set(1.0))
        self.after(0, lambda: self._log(
            f"\n完成！共產生至: {output}"))

        # 保存寄送所需狀態
        self._last_month_dir = month_dir
        self._last_receipt_lookup = receipt_lookup
        self._last_year = year
        self._last_month = month

        self.after(0, lambda: messagebox.showinfo(
            "完成", f"所有文件已產生！\n\n輸出至: {output}\n\n如需寄送，請按「預覽並寄送 Gmail」。"))
        self.after(0, lambda: os.startfile(output))

    # ──────────────────────────────────────────────────────
    # Gmail 寄送
    # ──────────────────────────────────────────────────────
    def _on_open_email_preview(self):
        sender = self.var_sender_email.get().strip()
        if not sender:
            messagebox.showwarning("缺少寄件者", "請在「6. Gmail 寄送設定」填入寄件 Gmail。")
            return
        if "@" not in sender:
            messagebox.showwarning("Email 格式錯誤", "寄件 Gmail 看起來不對，請確認。")
            return

        # 取得 year / month / month_dir：優先用本次產生的結果，
        # 否則用目前 UI 上的年月 + 輸出資料夾推算（支援既有資料夾）
        try:
            year = int(self.var_year.get())
            month = int(self.var_month.get())
        except (ValueError, TypeError):
            messagebox.showerror("錯誤", "申報年度/月份必須是數字")
            return

        output = self.var_output.get().strip()
        if not output:
            messagebox.showwarning("缺少輸出位置", "請在「5. 輸出位置」指定輸出資料夾。")
            return

        prefix = f"{year}年{month:02d}月"
        month_dir = self._last_month_dir
        if not month_dir or not os.path.isdir(month_dir) \
                or self._last_year != year or self._last_month != month:
            month_dir = os.path.join(output, prefix)

        if not os.path.isdir(month_dir):
            messagebox.showwarning(
                "找不到月份資料夾",
                f"找不到：\n{month_dir}\n\n請先按「產生文件」，或確認年月/輸出位置正確。")
            return

        # 個資檔：用本次產生的，或重新讀一次
        receipt_lookup = self._last_receipt_lookup or {}
        if not receipt_lookup:
            db_path = self.var_people_db.get().strip()
            if db_path and os.path.exists(db_path):
                receipt_lookup = load_people_db(db_path)

        self._log("\n── 掃描合併 PDF，建立寄送清單 ──")
        self._log(f"  目錄：{month_dir}")
        jobs = build_email_jobs(month_dir, receipt_lookup, year, month)
        if not jobs:
            messagebox.showinfo(
                "無可寄送項目",
                f"在下列目錄找不到合併 PDF：\n{month_dir}\n\n"
                "預期結構為 *領據/PDF/**/*.pdf。請確認已產生領據文件。")
            return

        total = len(jobs)
        sendable = sum(1 for j in jobs if j.status == "pending")
        self._log(f"  共 {total} 位人員 / 可寄送 {sendable} 位")

        EmailPreviewWindow(self, jobs, sender)


# ──────────────────────────────────────────────────────────
# 寄送預覽視窗
# ──────────────────────────────────────────────────────────
class EmailPreviewWindow(ctk.CTkToplevel):
    """列出所有 EmailJob，可勾選、預覽、批次寄送。"""

    COL_WIDTHS = [(36, "☑"), (110, "姓名"), (110, "角色"),
                  (200, "診所"), (220, "Email"), (60, "附件"),
                  (120, "狀態")]

    def __init__(self, master, jobs: list[EmailJob], sender_email: str):
        super().__init__(master)
        self.title("Gmail 寄送預覽")
        self.geometry("980x640")
        self.minsize(900, 500)

        self.jobs = jobs
        self.sender_email = sender_email
        self._row_widgets: list[dict] = []  # 每列 UI 元件參照

        self._build_ui()
        self._refresh_rows()

        # 顯示後置前
        self.after(100, self.lift)
        self.after(150, self.focus_force)

    def _build_ui(self):
        # 頂部資訊
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=(15, 8))

        ctk.CTkLabel(top, text=f"寄件者： {self.sender_email}",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        ctk.CTkLabel(top, text=f"  |  共 {len(self.jobs)} 位人員",
                     text_color="gray50").pack(side="left")

        # 操作列
        ops = ctk.CTkFrame(self, fg_color="transparent")
        ops.pack(fill="x", padx=15, pady=(0, 8))

        ctk.CTkButton(ops, text="全選", width=80, height=30,
                      fg_color="gray60", hover_color="gray50",
                      command=self._select_all).pack(side="left", padx=(0, 6))
        ctk.CTkButton(ops, text="全不選", width=80, height=30,
                      fg_color="gray60", hover_color="gray50",
                      command=self._select_none).pack(side="left", padx=(0, 6))
        ctk.CTkButton(ops, text="僅選可寄送", width=100, height=30,
                      fg_color="gray60", hover_color="gray50",
                      command=self._select_sendable).pack(side="left", padx=(0, 6))

        self.btn_send = ctk.CTkButton(
            ops, text="✉ 確認寄送勾選項目", width=180, height=32,
            fg_color="#1e8449", hover_color="#196f3d",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_send_clicked)
        self.btn_send.pack(side="right")

        # 表格標題列
        hdr = ctk.CTkFrame(self, height=30)
        hdr.pack(fill="x", padx=15)
        for i, (w, title) in enumerate(self.COL_WIDTHS):
            lbl = ctk.CTkLabel(hdr, text=title, width=w,
                               font=ctk.CTkFont(size=12, weight="bold"),
                               anchor="w")
            lbl.grid(row=0, column=i, padx=4, sticky="w")

        # 可滾動表格
        self.table = ctk.CTkScrollableFrame(self, height=420)
        self.table.pack(fill="both", expand=True, padx=15, pady=(4, 10))

        # 底部狀態列
        self.status_lbl = ctk.CTkLabel(self, text="",
                                       text_color="gray40",
                                       font=ctk.CTkFont(size=11),
                                       anchor="w")
        self.status_lbl.pack(fill="x", padx=15, pady=(0, 10))

    def _refresh_rows(self):
        # 清掉舊列
        for w in self.table.winfo_children():
            w.destroy()
        self._row_widgets.clear()

        for idx, job in enumerate(self.jobs):
            row = ctk.CTkFrame(self.table,
                               fg_color=("gray92", "gray20") if idx % 2 else "transparent")
            row.pack(fill="x", pady=1)

            # 勾選框
            var = ctk.BooleanVar(value=job.selected)
            chk = ctk.CTkCheckBox(row, text="", variable=var, width=24,
                                  command=lambda j=job, v=var: self._toggle(j, v))
            chk.grid(row=0, column=0, padx=4, pady=4)

            # 其他欄位
            values = [
                (110, job.person_name),
                (110, job.role or "—"),
                (200, job.clinic_name or "—"),
                (220, job.to_email or "—"),
                (60, str(len(job.attachments))),
            ]
            for col_i, (w, text) in enumerate(values, start=1):
                lbl = ctk.CTkLabel(row, text=text, width=w, anchor="w",
                                   font=ctk.CTkFont(size=12))
                lbl.grid(row=0, column=col_i, padx=4, sticky="w")

            status_lbl = ctk.CTkLabel(row, text=self._status_text(job),
                                      text_color=self._status_color(job),
                                      width=120, anchor="w",
                                      font=ctk.CTkFont(size=12))
            status_lbl.grid(row=0, column=6, padx=4, sticky="w")

            # 預覽按鈕
            btn_preview = ctk.CTkButton(
                row, text="預覽", width=56, height=24,
                font=ctk.CTkFont(size=11),
                fg_color="gray55", hover_color="gray45",
                command=lambda j=job: self._preview_job(j))
            btn_preview.grid(row=0, column=7, padx=(8, 4))

            # 禁用不可寄送的勾選框
            if job.status == "skipped":
                chk.configure(state="disabled")

            self._row_widgets.append({
                "job": job, "chk_var": var, "chk": chk,
                "status_lbl": status_lbl, "btn_preview": btn_preview,
            })

        self._update_status_bar()

    def _status_text(self, job: EmailJob) -> str:
        m = {
            "pending": "待寄送",
            "sent": "✓ 已寄出",
            "failed": "✗ 失敗",
            "skipped": f"跳過（{job.error}）" if job.error else "跳過",
        }
        return m.get(job.status, job.status)

    def _status_color(self, job: EmailJob) -> str:
        return {
            "pending": "gray40",
            "sent": "#1e8449",
            "failed": "#c0392b",
            "skipped": "#b7950b",
        }.get(job.status, "gray40")

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

    def _update_status_bar(self):
        selected = sum(1 for j in self.jobs if j.selected and j.is_sendable)
        skipped = sum(1 for j in self.jobs if j.status == "skipped")
        sent = sum(1 for j in self.jobs if j.status == "sent")
        failed = sum(1 for j in self.jobs if j.status == "failed")
        total_bytes = sum(
            j.total_attachment_bytes for j in self.jobs if j.selected and j.is_sendable
        )
        mb = total_bytes / (1024 * 1024)
        self.status_lbl.configure(
            text=f"將寄送 {selected} 封（附件合計 {mb:.1f} MB）  |  "
                 f"跳過 {skipped}  |  已寄出 {sent}  |  失敗 {failed}"
        )

    def _preview_job(self, job: EmailJob):
        win = ctk.CTkToplevel(self)
        win.title(f"預覽 — {job.person_name}")
        win.geometry("680x520")
        win.transient(self)

        # 主旨
        frm = ctk.CTkFrame(win, fg_color="transparent")
        frm.pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkLabel(frm, text="主旨：",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
        ctk.CTkLabel(frm, text=job.subject, anchor="w").pack(
            side="left", fill="x", expand=True, padx=(8, 0))

        # 收件者
        frm2 = ctk.CTkFrame(win, fg_color="transparent")
        frm2.pack(fill="x", padx=15, pady=2)
        ctk.CTkLabel(frm2, text="收件者：",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
        ctk.CTkLabel(frm2, text=job.to_email or "（無）",
                     anchor="w").pack(side="left", padx=(8, 0))

        # 內文
        ctk.CTkLabel(win, text="內文：",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(fill="x", padx=15, pady=(10, 2))
        txt = ctk.CTkTextbox(win, height=220,
                             font=ctk.CTkFont(family="Microsoft JhengHei", size=12))
        txt.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        txt.insert("1.0", job.body)
        txt.configure(state="disabled")

        # 附件
        ctk.CTkLabel(win, text=f"附件（{len(job.attachments)}）：",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(fill="x", padx=15, pady=(6, 2))
        att_box = ctk.CTkTextbox(win, height=110,
                                 font=ctk.CTkFont(family="Consolas", size=11))
        att_box.pack(fill="both", expand=False, padx=15, pady=(0, 15))
        for p in job.attachments:
            att_box.insert("end", f"{p}\n")
        att_box.configure(state="disabled")

    def _on_send_clicked(self):
        selected_jobs = [j for j in self.jobs if j.selected and j.is_sendable]
        if not selected_jobs:
            messagebox.showinfo("無可寄送項目", "沒有勾選任何可寄送的信件。")
            return

        # 輸入 App Password
        pw_dialog = ctk.CTkInputDialog(
            title="Gmail App Password",
            text=f"即將寄送 {len(selected_jobs)} 封信。\n"
                 f"請輸入 {self.sender_email} 的 App Password：")
        app_password = pw_dialog.get_input()
        if not app_password:
            return
        # 移除所有空白字元（含 unicode 空白、零寬字元、換行、tab 等）
        app_password = "".join(
            c for c in app_password
            if not c.isspace() and c not in "\u200b\u200c\u200d\ufeff\u00a0"
        )
        # 只保留可列印 ASCII（App Password 只有 a-z 字母）
        app_password = "".join(c for c in app_password if 32 < ord(c) < 127)
        if not app_password:
            messagebox.showwarning("未輸入密碼", "已取消寄送。")
            return
        # 檢查長度 — App Password 標準為 16 碼
        if len(app_password) != 16:
            if not messagebox.askyesno(
                "密碼長度異常",
                f"你輸入的密碼長度為 {len(app_password)} 字元，"
                f"Gmail App Password 標準為 16 字元。\n\n"
                f"是否仍要嘗試送出？（可能會被 Google 拒絕）",
            ):
                return

        # 二次確認
        if not messagebox.askyesno(
            "確認寄送",
            f"即將寄送 {len(selected_jobs)} 封 Gmail。\n\n"
            f"寄件者：{self.sender_email}\n"
            f"附件合計：{sum(j.total_attachment_bytes for j in selected_jobs) / 1024 / 1024:.1f} MB\n\n"
            f"確認繼續？",
        ):
            return

        self.btn_send.configure(state="disabled", text="寄送中…")
        threading.Thread(
            target=self._send_worker,
            args=(selected_jobs, app_password),
            daemon=True,
        ).start()

    def _send_worker(self, selected_jobs: list[EmailJob], app_password: str):
        total = len(selected_jobs)
        auth_error = False
        for idx, job in enumerate(selected_jobs, 1):
            self.after(0, lambda j=job: self._mark_status(j, "sending"))
            try:
                send_via_gmail_smtp(self.sender_email, app_password, job)
            except SmtpAuthError as e:
                auth_error = True
                self.after(0, lambda msg=str(e): messagebox.showerror(
                    "Gmail 認證失敗", msg))
                break
            except Exception:
                pass  # 錯誤已記在 job
            finally:
                self.after(0, lambda j=job: self._mark_status(j, j.status))

        # 完成
        self.after(0, lambda: self.btn_send.configure(
            state="normal", text="✉ 確認寄送勾選項目"))
        if not auth_error:
            sent = sum(1 for j in selected_jobs if j.status == "sent")
            failed = sum(1 for j in selected_jobs if j.status == "failed")
            self.after(0, lambda: messagebox.showinfo(
                "寄送完成",
                f"成功：{sent}\n失敗：{failed}\n總計：{total}"))

    def _mark_status(self, job: EmailJob, display_status: str):
        """即時更新某 job 的狀態欄。"""
        for rw in self._row_widgets:
            if rw["job"] is job:
                if display_status == "sending":
                    rw["status_lbl"].configure(text="寄送中…", text_color="gray40")
                else:
                    rw["status_lbl"].configure(
                        text=self._status_text(job),
                        text_color=self._status_color(job))
                break
        self._update_status_bar()


if __name__ == "__main__":
    app = App()
    app.mainloop()
