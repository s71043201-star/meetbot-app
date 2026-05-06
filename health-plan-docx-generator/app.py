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
from email_sender import build_email_jobs
from email_preview import EmailPreviewWindow
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

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# 全域字型:Windows 下中文友善 + 較清晰的字級
try:
    ctk.ThemeManager.theme["CTkFont"]["family"] = "Microsoft JhengHei UI"
    ctk.ThemeManager.theme["CTkFont"]["size"] = 13
    ctk.ThemeManager.theme["CTkFont"]["weight"] = "normal"
except Exception:
    pass

UI_FONT = "Microsoft JhengHei UI"
MONO_FONT = "Cascadia Mono"  # Windows 11 內建,比 Consolas 清晰


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("⚡ 健康台灣深耕計畫 — 核銷文件產生器")
        self.geometry("820x820")
        self.minsize(740, 640)
        self.configure(fg_color="#0f1419")  # 深色背景

        # 進階篩選:勾選要產生的診所(None = 全部,維持預設行為)
        self._selected_clinics: set[str] | None = None

        self._build_ui()

    def _build_ui(self):
        # Scrollable main frame(深色科技風)
        main = ctk.CTkScrollableFrame(
            self, fg_color="#0f1419",
            scrollbar_button_color="#1f2933",
            scrollbar_button_hover_color="#2c3e50")
        main.pack(fill="both", expand=True, padx=18, pady=18)

        # ── 頂部標題 Banner ──
        banner = ctk.CTkFrame(main, fg_color="#1a2332", corner_radius=12,
                              border_width=1, border_color="#2c3e50")
        banner.pack(fill="x", pady=(0, 15))
        title_inner = ctk.CTkFrame(banner, fg_color="transparent")
        title_inner.pack(padx=20, pady=14)
        ctk.CTkLabel(title_inner, text="⚡  核銷文件產生器",
                     font=ctk.CTkFont(size=26, weight="bold"),
                     text_color="#3498db").pack(side="left")
        ctk.CTkLabel(title_inner, text="  v37",
                     font=ctk.CTkFont(family=MONO_FONT, size=13),
                     text_color="#52b3e2").pack(side="left", padx=(10, 0))
        ctk.CTkLabel(banner, text="台北市醫師公會 ◆ 健康台灣深耕計畫",
                     font=ctk.CTkFont(size=12),
                     text_color="#a0aec0").pack(pady=(0, 12))

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
            text_color="#a0aec0", font=ctk.CTkFont(size=12)
        ).pack(side="left", padx=12)

        # ── 產出選項 ──
        self._section_label(main, "3. 選擇要產生的文件 (勾選 = 該資料夾才會產出)")
        frame_opts = ctk.CTkFrame(main, corner_radius=10)
        frame_opts.pack(fill="x", pady=(0, 10))

        opts_inner = ctk.CTkFrame(frame_opts, fg_color="transparent")
        opts_inner.pack(padx=15, pady=10, fill="x")

        # ── 子變數(後端用) ──
        # 醫師類
        self.var_gen_doctor_presc_detail = ctk.BooleanVar(value=True)
        self.var_gen_doctor_exec_detail = ctk.BooleanVar(value=True)
        self.var_gen_doctor_receipt = ctk.BooleanVar(value=True)
        self.var_gen_doctor_summary = ctk.BooleanVar(value=True)
        # 診所類(健康管理費)
        self.var_gen_health_detail = ctk.BooleanVar(value=True)
        self.var_gen_health_receipt = ctk.BooleanVar(value=True)
        self.var_gen_health_summary = ctk.BooleanVar(value=True)
        # 課程老師類(處方處置費)
        self.var_gen_treatment_detail = ctk.BooleanVar(value=True)
        self.var_gen_treatment_receipt = ctk.BooleanVar(value=True)
        self.var_gen_treatment_summary = ctk.BooleanVar(value=True)

        # ── 三大群組設定(主 toggle + 詳情視窗) ──
        # items: (BooleanVar, 資料夾名稱, 簡短描述)
        self._gen_groups = [
            {
                "key": "doctor",
                "title": "【醫師】處方費 / 處方執行費",
                "items": [
                    (self.var_gen_doctor_presc_detail,
                     "處方處方費民眾明細/",
                     "每位醫師的處方費民眾明細表"),
                    (self.var_gen_doctor_exec_detail,
                     "處方執行費民眾明細/",
                     "每位醫師的處方執行費民眾明細表"),
                    (self.var_gen_doctor_receipt,
                     "處方處方費與處方執行費領據/",
                     "每位醫師合併的領據(處方費 + 執行費)"),
                    (self.var_gen_doctor_summary,
                     "其他內容/處方費、處方執行費總表明細表合併檔與Excel/",
                     "醫師彙整總表(全部合併) + Excel 統計檔"),
                ],
            },
            {
                "key": "health",
                "title": "【診所】健康管理費",
                "items": [
                    (self.var_gen_health_detail,
                     "健康管理費民眾明細/",
                     "每間診所的民眾明細表"),
                    (self.var_gen_health_receipt,
                     "健康管理費領據/",
                     "每間診所的領據(對應診所行政人員)"),
                    (self.var_gen_health_summary,
                     "其他內容/健康管理費合併總表與個人excel/",
                     "健管費彙整總表 + 各診所個別 Excel"),
                ],
            },
            {
                "key": "treatment",
                "title": "【課程老師】處方處置費",
                "items": [
                    (self.var_gen_treatment_detail,
                     "處方處置費民眾明細/",
                     "每位老師的民眾明細表"),
                    (self.var_gen_treatment_receipt,
                     "處方處置費領據/",
                     "每位老師的領據"),
                    (self.var_gen_treatment_summary,
                     "其他內容/處方處置費合併總表word/",
                     "處方處置費核銷總表 + 執行人員民眾明細表(合併版)"),
                ],
            },
        ]

        self._gen_group_main_vars: dict = {}
        self._gen_group_status_lbls: dict = {}
        self._suppress_group_sync = False

        for g in self._gen_groups:
            block = ctk.CTkFrame(opts_inner, corner_radius=8,
                                 fg_color=("gray92", "gray22"))
            block.pack(fill="x", pady=4)

            row = ctk.CTkFrame(block, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=8)

            main_var = ctk.BooleanVar(value=True)
            self._gen_group_main_vars[g["key"]] = main_var

            chk = ctk.CTkCheckBox(
                row, text=g["title"], variable=main_var,
                font=ctk.CTkFont(size=13, weight="bold"),
                command=lambda gk=g["key"]: self._on_group_main_clicked(gk))
            chk.pack(side="left")

            status_lbl = ctk.CTkLabel(row, text="", text_color="#a0aec0",
                                       font=ctk.CTkFont(size=11))
            status_lbl.pack(side="left", padx=(15, 0))
            self._gen_group_status_lbls[g["key"]] = status_lbl

            ctk.CTkButton(row, text="詳情 ▼", width=80, height=28,
                          fg_color="#2980b9", hover_color="#1f618d",
                          font=ctk.CTkFont(size=11),
                          command=lambda gk=g["key"]:
                              self._open_group_detail(gk)
                          ).pack(side="right")

            for sub_var, _, _ in g["items"]:
                sub_var.trace_add(
                    "write",
                    lambda *a, gk=g["key"]: self._update_group_status(gk))
            self._update_group_status(g["key"])

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
                     text_color="#a0aec0", font=ctk.CTkFont(size=12)).pack(
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
                     text_color="#a0aec0", font=ctk.CTkFont(size=12)).pack(
                         side="left", padx=8)

        # 進階篩選:選擇要產生的診所
        frame_rg3 = ctk.CTkFrame(main, fg_color="transparent")
        frame_rg3.pack(fill="x", pady=(0, 10))
        ctk.CTkButton(frame_rg3, text="📋 選擇要產生的診所", width=170, height=32,
                      fg_color="#2980b9", hover_color="#1f618d",
                      command=self._open_clinic_selector).pack(side="left")
        self.lbl_clinic_filter = ctk.CTkLabel(
            frame_rg3, text="目前: 全部診所 (預設)",
            text_color="#a0aec0", font=ctk.CTkFont(size=12))
        self.lbl_clinic_filter.pack(side="left", padx=12)
        ctk.CTkButton(frame_rg3, text="重設", width=60, height=28,
                      fg_color="gray60", hover_color="gray50",
                      font=ctk.CTkFont(size=11),
                      command=self._reset_clinic_filter).pack(side="right")

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
                     text_color="#a0aec0",
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

        # ── Pac-Man 進度動畫 ──
        # 真正在「批次轉 PDF」時會逐檔餵進來,平時待機嘴巴一開一合
        try:
            from pacman_animator import PacManAnimator
            self.pacman = PacManAnimator(main)
            self.pacman.pack(fill="x", pady=(0, 6))
        except Exception as e:
            # 萬一 Pillow / 素材載入失敗,動畫不要拖累主功能
            self.pacman = None
            print(f"[App] PacManAnimator 啟用失敗: {e}")

        # ── Progress ──
        self.progress = ctk.CTkProgressBar(main)
        self.progress.pack(fill="x", pady=(0, 5))
        self.progress.set(0)

        # ── 日誌 ──
        self.log = ctk.CTkTextbox(main, height=150,
                                  font=ctk.CTkFont(family=MONO_FONT, size=11))
        self.log.pack(fill="both", expand=True)

    def _section_label(self, parent, text):
        # 加上前綴裝飾線、強調色文字
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="x", pady=(14, 4))
        ctk.CTkLabel(wrap, text="┃", text_color="#3498db",
                     font=ctk.CTkFont(size=18, weight="bold")
                     ).pack(side="left", padx=(0, 4))
        ctk.CTkLabel(wrap, text=text,
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#dde6ed",
                     anchor="w").pack(side="left", fill="x", expand=True)

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
            # 換檔可能造成清單變動,重設診所篩選
            self._selected_clinics = None
            if hasattr(self, "lbl_clinic_filter"):
                self._update_clinic_filter_label()

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

    # ── 進階:選擇診所 ──
    def _open_clinic_selector(self):
        regions_path = self.var_regions_db.get().strip()
        regions_map = regions_mod.load_regions(regions_path)
        if not regions_map or not any(regions_map.values()):
            messagebox.showwarning(
                "找不到診所清單",
                "診所分區檔不存在或為空白,請先設定。")
            return
        # 嘗試從處方 Excel 取「未分區」的診所(歸「其他」群組)
        extra_clinics: list[str] = []
        excel_path = self.var_excel.get().strip()
        if excel_path and os.path.exists(excel_path):
            try:
                raw = read_raw_records(excel_path)
                clinics_in_excel = {
                    str(r[7]).strip() for r in raw
                    if len(r) > 7 and r[7] and str(r[7]).strip()
                }
                listed = set()
                for cs in regions_map.values():
                    listed.update(cs)
                # 沒被分區檔列到 + 不能 fuzzy match 的,才視為「其他」
                for c in sorted(clinics_in_excel):
                    if regions_mod.find_region(c, regions_map) is None \
                            and c not in listed:
                        extra_clinics.append(c)
            except Exception:
                pass

        ClinicSelectorWindow(self, regions_map, extra_clinics)

    def _update_clinic_filter_label(self):
        if not hasattr(self, "lbl_clinic_filter"):
            return
        sel = self._selected_clinics
        if sel is None:
            self.lbl_clinic_filter.configure(
                text="目前: 全部診所 (預設)", text_color="#a0aec0")
        elif not sel:
            self.lbl_clinic_filter.configure(
                text="目前: 未勾選任何診所 (不會產出)", text_color="#c0392b")
        else:
            n = len(sel)
            preview = ", ".join(list(sel)[:3])
            if n > 3:
                preview += f" 等 {n} 間"
            else:
                preview = f"已選 {n} 間: {preview}"
            self.lbl_clinic_filter.configure(
                text=f"目前: {preview}", text_color="#2980b9")

    def _reset_clinic_filter(self):
        self._selected_clinics = None
        self._update_clinic_filter_label()

    # ── 產出選項群組:主 toggle / 狀態 / 詳情視窗 ──
    def _get_group(self, group_key: str):
        for g in self._gen_groups:
            if g["key"] == group_key:
                return g
        raise KeyError(group_key)

    def _on_group_main_clicked(self, group_key: str):
        """user 點主 checkbox 時:同步全部子勾選為 main_var 的值。"""
        main_var = self._gen_group_main_vars[group_key]
        target = main_var.get()
        g = self._get_group(group_key)
        self._suppress_group_sync = True
        try:
            for sub_var, _, _ in g["items"]:
                sub_var.set(target)
        finally:
            self._suppress_group_sync = False
        self._update_group_status(group_key)

    def _update_group_status(self, group_key: str):
        """子變動時:更新狀態 label 並同步主 checkbox 顯示。"""
        if self._suppress_group_sync:
            return
        g = self._get_group(group_key)
        n = sum(1 for sub_var, _, _ in g["items"] if sub_var.get())
        total = len(g["items"])
        lbl = self._gen_group_status_lbls[group_key]
        main_var = self._gen_group_main_vars[group_key]

        # 同步主 checkbox 視覺狀態(主 var 沒被 trace,不會循環)
        if n == total:
            if not main_var.get():
                main_var.set(True)
            lbl.configure(text=f"{total}/{total} 項全部產出",
                          text_color="#1e8449")
        elif n == 0:
            if main_var.get():
                main_var.set(False)
            lbl.configure(text="整組不產出", text_color="#c0392b")
        else:
            if main_var.get():
                main_var.set(False)
            lbl.configure(text=f"部分產出 ({n}/{total} 項)",
                          text_color="#d68910")

    def _open_group_detail(self, group_key: str):
        g = self._get_group(group_key)
        GroupDetailWindow(self, g)

    @staticmethod
    def _clinic_matches_selection(institution: str, selected: set[str]) -> bool:
        """institution 是否對應到 selected 中任一診所(精確/子字串/前綴 ≥3)。"""
        if not institution:
            return False
        if institution in selected:
            return True
        for s in selected:
            if s and (s in institution or institution in s):
                return True
        for s in selected:
            if not s:
                continue
            plen = 0
            for a, b in zip(institution, s):
                if a == b:
                    plen += 1
                else:
                    break
            if plen >= 3:
                return True
        return False

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

        all_pending_docx: list[str] = []
        health_merge_info = None
        executor_merge_info = None
        doctor_merge_info = None

        # ───────────── 醫師類:彙整總表(其他內容/處方費...合併檔與Excel/) ─────────────
        if self.var_gen_doctor_summary.get() and data.doctors:
            d = agg_subdir(COMBINED_DIR_NAME)
            # Excel 統計檔
            try:
                generate_prescription_fee_excel(
                    raw_records_issuance, prefix, d)
                generate_execution_fee_excel(
                    raw_records_execution, prefix, d)
            except Exception:
                pass
            # 處方費總表 docx
            path1 = os.path.join(
                d, f"健康台灣深耕計畫_處方費-總表-{prefix}.docx")
            tmpl1 = DEFAULT_TEMPLATES["prescription"]
            if os.path.exists(tmpl1):
                generate_prescription_fee_from_template(tmpl1, data, path1)
            else:
                generate_prescription_fee_doc(data, path1)
            all_pending_docx.append(os.path.abspath(path1))
            # 處方執行費總表 docx
            path2 = os.path.join(
                d, f"健康台灣深耕計畫_處方執行費核銷總表-{prefix}.docx")
            tmpl2 = DEFAULT_TEMPLATES["execution"]
            if os.path.exists(tmpl2):
                generate_execution_fee_from_template(tmpl2, data, path2)
            else:
                generate_execution_fee_doc(data, path2)
            all_pending_docx.append(os.path.abspath(path2))
            self.after(0, lambda s=scope_label: self._log(
                f"[{s}] 處方費、處方執行費總表明細表合併檔與Excel"))
            step_cb()

        # ───────── 醫師類:每醫師個別 民眾明細 + 領據 ─────────
        emit_dpd = self.var_gen_doctor_presc_detail.get()
        emit_ded = self.var_gen_doctor_exec_detail.get()
        emit_dr = self.var_gen_doctor_receipt.get()
        if (emit_dpd or emit_ded or emit_dr) and data.doctors:
            dr_info = generate_doctor_receipts(
                data, month_dir,
                receipt_lookup=receipt_lookup,
                also_pdf=False,
                emit_presc_detail=emit_dpd,
                emit_exec_detail=emit_ded,
                emit_receipt=emit_dr,
            )
            if dr_info:
                doctor_merge_info = dr_info
                seen = set()
                for _, _, dd, r, _ in dr_info:
                    for p in (dd, r):
                        if p and p not in seen:
                            all_pending_docx.append(p)
                            seen.add(p)
            count = sum(1 for doc in data.doctors
                        if doc.prescription_fee > 0 or doc.execution_fee > 0)
            parts = []
            if emit_dpd:
                parts.append("處方處方費民眾明細")
            if emit_ded:
                parts.append("處方執行費民眾明細")
            if emit_dr:
                parts.append("處方處方費與處方執行費領據")
            self.after(0, lambda s=scope_label, c=count,
                       p="、".join(parts):
                       self._log(f"[{s}] {p} ({c} 位醫師)"))
            step_cb()

        # ───────── 診所類:彙整總表(其他內容/健康管理費合併總表與個人excel/) ─────────
        if self.var_gen_health_summary.get() and data.health_mgmts:
            d = agg_subdir(HEALTH_COMBINED_DIR)
            # Excel 統計檔
            try:
                generate_health_mgmt_excel(raw_records_issuance, prefix, d)
            except Exception:
                pass
            # 健管費總表 docx
            path = os.path.join(
                d, f"健康台灣深耕計畫_健康管理費總表-{prefix}.docx")
            generate_health_mgmt_doc(data, path, min_prescriptions=min_presc)
            all_pending_docx.append(os.path.abspath(path))
            # 個別 Excel
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
            self.after(0, lambda s=scope_label, x=len(xlsx_paths): self._log(
                f"[{s}] 健康管理費合併總表與個人excel (個別Excel×{x})"))
            step_cb()

        # ───────── 診所類:每診所個別 民眾明細 + 領據 ─────────
        emit_hd = self.var_gen_health_detail.get()
        emit_hr = self.var_gen_health_receipt.get()
        if (emit_hd or emit_hr) and data.health_mgmts:
            hm_result = generate_health_mgmt_individual_docs(
                data, month_dir,
                receipt_lookup=receipt_lookup, also_pdf=False,
                emit_detail=emit_hd, emit_receipt=emit_hr,
            )
            if hm_result:
                hm_docx_info, hm_receipt_dir = hm_result
                health_merge_info = (hm_docx_info, hm_receipt_dir)
                for _, dd, r in hm_docx_info:
                    for p in (dd, r):
                        if p:
                            all_pending_docx.append(p)
            hm_count = sum(1 for hm in data.health_mgmts if hm.is_qualified)
            parts = []
            if emit_hd:
                parts.append("健康管理費民眾明細")
            if emit_hr:
                parts.append("健康管理費領據")
            self.after(0, lambda s=scope_label, c=hm_count,
                       p="、".join(parts):
                       self._log(f"[{s}] {p} ({c} 間診所)"))
            step_cb()

        # ───────── 課程老師類:彙整總表(其他內容/處方處置費合併總表word/) ─────────
        if produce_executor and self.var_gen_treatment_summary.get() \
                and data.executors:
            d = agg_subdir(TREATMENT_COMBINED_DIR)
            # 核銷總表
            p1 = os.path.join(
                d, f"健康台灣深耕計畫_處方處置費核銷總表-{prefix}.docx")
            generate_treatment_fee_doc(data, p1)
            # 執行人員民眾明細表(合併版)
            p2 = os.path.join(
                d, f"健康台灣深耕計畫_執行人員民眾明細表-{prefix}.docx")
            generate_executor_patient_list_doc(data, p2)
            self.after(0, lambda s=scope_label: self._log(
                f"[{s}] 處方處置費合併總表word"))
            step_cb()

        # ───────── 課程老師類:每老師個別 民眾明細 + 領據 ─────────
        emit_td = self.var_gen_treatment_detail.get()
        emit_tr = self.var_gen_treatment_receipt.get()
        if produce_executor and (emit_td or emit_tr) and data.executors:
            ex_result = generate_executor_merged_docs(
                data, month_dir, also_pdf=False,
                receipt_lookup=receipt_lookup,
                emit_detail=emit_td, emit_receipt=emit_tr,
            )
            if ex_result:
                ex_docx_info, ex_receipt_dir = ex_result
                executor_merge_info = (ex_docx_info, ex_receipt_dir)
                for _, _, dd, r in ex_docx_info:
                    for p in (dd, r):
                        if p:
                            all_pending_docx.append(p)
            # 同一人多處方類型會拆成多筆 ExecutorData,計數時依姓名去重
            count = len({ex.executor_name for ex in data.executors
                         if ex.receipt and ex.receipt.amount > 0})
            parts = []
            if emit_td:
                parts.append("處方處置費民眾明細")
            if emit_tr:
                parts.append("處方處置費領據")
            self.after(0, lambda s=scope_label, c=count,
                       p="、".join(parts):
                       self._log(f"[{s}] {p} ({c} 位老師)"))
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

        # 讀取總資料(read_prescription_report 只用一次,分區時再 filter)
        # min_prescriptions 統一傳 0,reader 不過濾任何診所;
        # 各區門檻在下方 per-scope 迴圈以 is_qualified 控制是否產出。
        # (舊版:傳 any_threshold 會用任一區的門檻砍掉所有診所,
        #  導致低門檻區(如 中山/士林=20)在高門檻區(如 北投=30) 存在時
        #  被誤判成「未達門檻」,只有大量資料的診所才會留下。)
        data = read_prescription_report(
            issuance_excel,
            execution_path=execution_excel,
            report_year=year, report_month=month,
            min_prescriptions=0,
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
            f"執行人員: {len({ex.executor_name for ex in data.executors})} 位\n"
        ))

        # 人員個資
        receipt_lookup = {}
        db_path = self.var_people_db.get().strip()
        if db_path and os.path.exists(db_path):
            self.after(0, lambda: self._log("讀取人員個資檔..."))
            receipt_lookup = load_people_db(db_path)

        # 診所名 → 人名(用於健管費 clinic_person 修正)
        # 修正:value 用 info.recipient_name 而非 dict key,避免取到
        # people_db 的內部佔位 key(如 "__clinic_only:診所名")。
        # 個資該列有姓名 → 填姓名;姓名空白 → "" (明確留空,不亂寫)
        clinic_to_person = {
            info.clinic_name: (info.recipient_name or "")
            for info in receipt_lookup.values()
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

        # ── 套用「進階:選擇要產生的診所」過濾 ──
        sel = self._selected_clinics
        if sel is not None:
            if not sel:
                self.after(0, lambda: self._log(
                    "⚠ 進階篩選:未勾選任何診所,將不會產出診所相關文件"))
                kept: set[str] = set()
            else:
                kept = {c for c in all_clinics
                        if self._clinic_matches_selection(c, sel)}
                self.after(0, lambda n=len(kept), t=len(all_clinics):
                           self._log(
                    f"\n[診所篩選] 鎖定 {n} 間 (共 {t} 間出現在處方 Excel)"))
            for r in list(region_to_clinics.keys()):
                region_to_clinics[r] = region_to_clinics[r] & kept
            all_clinics = kept

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

        # scope tuple: (label, allowed_clinics, min_presc, month_dir, produce_executor)
        scopes: list[tuple[str, set[str], int, str, bool]] = []
        if region_choice == "全部":
            # 改:不再產出「全部/」資料夾(內容跟北投+士林+中山+其他重複)
            # 改:處方處置費(課程老師)跨區共用,獨立放「課程老師/」資料夾
            for r in regions_mod.REGION_NAMES:
                clinics = region_to_clinics.get(r, set())
                if clinics:
                    scopes.append((
                        r, clinics,
                        region_thresholds.get(r, 0),
                        os.path.join(month_dir_root, r),
                        False))
            if unclassified:
                scopes.append((
                    "其他", unclassified, 0,
                    os.path.join(month_dir_root, "其他"),
                    False))
            # 處方處置費獨立 scope(只產 executor 相關文件)
            if data.executors:
                scopes.append((
                    "課程老師", set(), 0,
                    os.path.join(month_dir_root, "課程老師"),
                    True))
        else:
            clinics = region_to_clinics.get(region_choice, set())
            if not clinics:
                self.after(0, lambda rc=region_choice: self._log(
                    f"⚠ 選擇的分區「{rc}」沒有任何診所"))
            scopes.append((
                region_choice, clinics,
                region_thresholds.get(region_choice, 0),
                os.path.join(month_dir_root, region_choice),
                True))  # 單區也產 executor

        self.after(0, lambda: self._log(
            f"\n產生範圍:{len(scopes)} 個 scope (不再產出『全部/』,可省 ~50% 時間)"))

        # ── 進度 ──
        any_doctor_per_person = (
            self.var_gen_doctor_presc_detail.get()
            or self.var_gen_doctor_exec_detail.get()
            or self.var_gen_doctor_receipt.get())
        any_health_per_person = (
            self.var_gen_health_detail.get()
            or self.var_gen_health_receipt.get())
        per_scope_steps = sum([
            self.var_gen_doctor_summary.get(),
            any_doctor_per_person,
            self.var_gen_health_summary.get(),
            any_health_per_person,
        ])
        any_treatment_per_person = (
            self.var_gen_treatment_detail.get()
            or self.var_gen_treatment_receipt.get())
        executor_steps_per = sum([
            self.var_gen_treatment_summary.get(),
            any_treatment_per_person,
        ])
        # 含 clinics 的 scope × per_scope_steps + 執行 executor 的 scope × executor_steps
        clinic_scope_count = sum(1 for _, allowed, _, _, _ in scopes if allowed)
        executor_scope_count = sum(1 for _, _, _, _, pe in scopes if pe)
        total_steps = (per_scope_steps * clinic_scope_count
                       + executor_steps_per * executor_scope_count)
        if total_steps == 0:
            total_steps = 1

        steps_done = 0

        # ── Pac-Man 動畫 Phase 1:Word 文件產生階段 ──
        # 此時產生的也是 Word docx,所以右側「已完成」用 Word 圖示
        # (尚未轉成 PDF)。step_cb 觸發時餵階段編號給動畫。
        if self.pacman is not None:
            placeholder = [f"第 {i + 1} 階段" for i in range(total_steps)]
            self.after(0, lambda t=total_steps, ph=placeholder:
                       self.pacman.start(t, ph, output_icon="word"))
            self.after(0, lambda: self.pacman.set_label(
                "Step 1/2:產生 Word 文件中…"))

        def step_cb():
            nonlocal steps_done
            steps_done += 1
            self.after(0, lambda: self.progress.set(
                0.1 + 0.85 * steps_done / total_steps))
            # 每完成一階段就餵 Pac-Man 一口(用階段編號當標籤)
            if self.pacman is not None:
                self.after(0, lambda d=steps_done:
                           self.pacman.feed(
                               in_name=f"第 {d} 階段",
                               out_name=f"第 {d} 階段"))

        # ── 逐 scope 產出 ──
        all_pending_docx: list[str] = []
        merge_bundles: list[tuple] = []  # (health, executor, doctor)

        for i, (scope_label, allowed, threshold, month_dir,
                produce_exec) in enumerate(scopes):
            # 過濾資料(每個 scope 都按該 scope 的 allowed_clinics 過濾;
            # executor 資料不受 clinic 過濾影響,_filter_data 中保留全部 executors)
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

            # ── Pac-Man 動畫 Phase 2:Word → PDF 批次轉檔 ──
            # 重新啟動 Pac-Man,清空 Phase 1 的階段編號,改用真實檔名,
            # output_icon='pdf' 讓右側顯示紅色 PDF 圖示
            todo_basenames = [os.path.basename(p) for p in all_pending_docx]
            if self.pacman is not None:
                self.after(0, lambda t=total_pdf, names=todo_basenames:
                           self.pacman.start(t, names, output_icon="pdf"))
                self.after(0, lambda: self.pacman.set_label(
                    "Step 2/2:Word → PDF 轉檔中…"))

            def _pdf_progress(done, total, name):
                # 每一份都餵 Pac-Man(每 ~150ms 一次,順)
                in_name = os.path.basename(name) if name else ""
                # 對應的 PDF 檔名(把 .docx 換成 .pdf)
                stem, _ = os.path.splitext(in_name)
                out_name = f"{stem}.pdf" if stem else ""
                if self.pacman is not None:
                    self.after(0, lambda i=in_name, o=out_name:
                               self.pacman.feed(i, o))
                if done % 10 == 0 or done == total:
                    self.after(0, lambda d=done, t=total, n=name:
                               self._log(f"  [{d}/{t}] {n}"))
            _convert_docx_list_to_pdf(all_pending_docx, progress_cb=_pdf_progress)
            self.after(0, lambda: self._log(
                f"[OK] {total_pdf} 份 PDF 轉換完成"))
            if self.pacman is not None:
                self.after(0, lambda: self.pacman.stop(finished=True))

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
# 產出選項群組詳情視窗
# ──────────────────────────────────────────────────────────
class GroupDetailWindow(ctk.CTkToplevel):
    """單一群組(醫師/診所/課程老師)的詳細產出選項視窗。

    顯示該群組可產出的所有資料夾,每個對應一個獨立 checkbox。
    """

    def __init__(self, master, group: dict):
        super().__init__(master)
        self.title(f"產出細項 — {group['title']}")
        self.geometry("720x520")
        self.minsize(580, 380)
        self.configure(fg_color=("gray95", "gray12"))

        self.group = group
        self._build_ui()
        self.transient(master)
        self.after(100, self.lift)
        self.after(150, self.focus_force)

    def _build_ui(self):
        # 頂部標題列
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=22, pady=(22, 4))
        ctk.CTkLabel(top, text="◢ " + self.group["title"],
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#3498db").pack(side="left")

        ctk.CTkLabel(
            self,
            text="勾選 = 該資料夾才會產出。每個資料夾獨立控制。",
            text_color="#a0aec0", font=ctk.CTkFont(size=11),
            anchor="w").pack(fill="x", padx=22, pady=(0, 8))

        # 操作列
        ops = ctk.CTkFrame(self, fg_color="transparent")
        ops.pack(fill="x", padx=22, pady=(0, 10))
        ctk.CTkButton(ops, text="✓ 全選", width=80, height=30,
                      fg_color="#2980b9", hover_color="#1f618d",
                      font=ctk.CTkFont(size=12),
                      command=self._select_all).pack(side="left", padx=(0, 6))
        ctk.CTkButton(ops, text="✕ 全不選", width=80, height=30,
                      fg_color="gray45", hover_color="gray35",
                      font=ctk.CTkFont(size=12),
                      command=self._select_none).pack(side="left")

        # 子項清單
        scroll = ctk.CTkScrollableFrame(
            self, fg_color=("gray97", "gray16"))
        scroll.pack(fill="both", expand=True, padx=22, pady=(0, 12))

        for sub_var, folder, desc in self.group["items"]:
            row = ctk.CTkFrame(scroll, fg_color=("white", "gray22"),
                               corner_radius=8, border_width=1,
                               border_color=("gray80", "gray30"))
            row.pack(fill="x", pady=5, padx=2)

            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=10)

            ctk.CTkCheckBox(inner, text="", variable=sub_var,
                            width=22, checkbox_width=20,
                            checkbox_height=20).pack(
                                side="left", padx=(0, 12))

            text_frame = ctk.CTkFrame(inner, fg_color="transparent")
            text_frame.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(
                text_frame, text="📁  " + folder,
                font=ctk.CTkFont(family=MONO_FONT, size=13,
                                 weight="bold"),
                text_color="#2980b9", anchor="w").pack(fill="x")
            ctk.CTkLabel(
                text_frame, text="    " + desc,
                font=ctk.CTkFont(size=11),
                text_color=("gray35", "gray70"), anchor="w").pack(fill="x")

        # 底部
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(fill="x", padx=22, pady=(0, 18))
        ctk.CTkButton(
            bot, text="完成", width=100, height=34,
            fg_color="#1e8449", hover_color="#196f3d",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.destroy).pack(side="right")

    def _select_all(self):
        for sub_var, _, _ in self.group["items"]:
            sub_var.set(True)

    def _select_none(self):
        for sub_var, _, _ in self.group["items"]:
            sub_var.set(False)


# ──────────────────────────────────────────────────────────
# 診所勾選視窗
# ──────────────────────────────────────────────────────────
class ClinicSelectorWindow(ctk.CTkToplevel):
    """讓使用者勾選要產生文件的診所(依分區分組)。"""

    def __init__(self, master, regions_map: dict, extra_clinics: list):
        super().__init__(master)
        self.title("選擇要產生的診所")
        self.geometry("520x680")
        self.minsize(450, 420)

        self.master_app = master
        self.regions_map = regions_map
        self.extra_clinics = list(extra_clinics or [])

        # 用主畫面當前狀態還原勾選
        prev = master._selected_clinics
        self.checks: dict[str, ctk.BooleanVar] = {}

        ordered: list[tuple[str, list[str]]] = []
        for r in regions_mod.REGION_NAMES:
            cs = regions_map.get(r, [])
            if cs:
                ordered.append((r, list(cs)))
        if self.extra_clinics:
            ordered.append(("其他 (處方 Excel 有但分區檔未列)", self.extra_clinics))
        self.ordered = ordered

        for _, cs in ordered:
            for c in cs:
                # 預設勾選:None → 全部勾;否則只勾在 set 內的
                if prev is None:
                    default = True
                else:
                    default = c in prev
                if c not in self.checks:
                    self.checks[c] = ctk.BooleanVar(value=default)

        self._build_ui()
        self.transient(master)
        self.after(100, self.lift)
        self.after(150, self.focus_force)

    def _build_ui(self):
        # 頂部說明
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkLabel(top, text="勾選要產生文件的診所",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")

        # 全選/全不選/反選
        ops = ctk.CTkFrame(self, fg_color="transparent")
        ops.pack(fill="x", padx=15, pady=(0, 6))
        ctk.CTkButton(ops, text="全選", width=70, height=28,
                      fg_color="gray60", hover_color="gray50",
                      command=self._select_all).pack(side="left", padx=(0, 5))
        ctk.CTkButton(ops, text="全不選", width=70, height=28,
                      fg_color="gray60", hover_color="gray50",
                      command=self._select_none).pack(side="left", padx=(0, 5))
        ctk.CTkButton(ops, text="反選", width=70, height=28,
                      fg_color="gray60", hover_color="gray50",
                      command=self._invert).pack(side="left", padx=(0, 5))

        # 滾動清單
        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=15, pady=(2, 6))

        for region_label, clinics in self.ordered:
            self._build_group(region_label, clinics)

        # 計數狀態
        self.count_lbl = ctk.CTkLabel(self, text="", text_color="#a0aec0",
                                      font=ctk.CTkFont(size=12), anchor="w")
        self.count_lbl.pack(fill="x", padx=15, pady=(0, 4))

        # 確認/取消
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(fill="x", padx=15, pady=(0, 15))
        ctk.CTkButton(bot, text="確認", width=90, height=34,
                      fg_color="#1e8449", hover_color="#196f3d",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._on_confirm).pack(side="right")
        ctk.CTkButton(bot, text="取消", width=80, height=34,
                      fg_color="gray60", hover_color="gray50",
                      command=self.destroy).pack(side="right", padx=(0, 6))

        self._update_count()

    def _build_group(self, region_label: str, clinics: list):
        header = ctk.CTkFrame(self.scroll, fg_color=("gray85", "gray25"),
                              corner_radius=4)
        header.pack(fill="x", pady=(8, 2))
        ctk.CTkLabel(header,
                     text=f"  📍 {region_label} ({len(clinics)} 間)",
                     font=ctk.CTkFont(size=13, weight="bold")
                     ).pack(side="left", pady=4)
        ctk.CTkButton(header, text="全不選", width=70, height=24,
                      fg_color="gray60", hover_color="gray50",
                      font=ctk.CTkFont(size=11),
                      command=lambda cs=clinics:
                          self._toggle_group(cs, False)
                      ).pack(side="right", padx=(2, 8), pady=2)
        ctk.CTkButton(header, text="全選", width=60, height=24,
                      fg_color="gray60", hover_color="gray50",
                      font=ctk.CTkFont(size=11),
                      command=lambda cs=clinics:
                          self._toggle_group(cs, True)
                      ).pack(side="right", padx=2, pady=2)

        for c in clinics:
            ctk.CTkCheckBox(self.scroll, text=c,
                            variable=self.checks[c],
                            command=self._update_count
                            ).pack(anchor="w", padx=20, pady=2)

    def _select_all(self):
        for v in self.checks.values():
            v.set(True)
        self._update_count()

    def _select_none(self):
        for v in self.checks.values():
            v.set(False)
        self._update_count()

    def _invert(self):
        for v in self.checks.values():
            v.set(not v.get())
        self._update_count()

    def _toggle_group(self, clinics: list, on: bool):
        for c in clinics:
            if c in self.checks:
                self.checks[c].set(on)
        self._update_count()

    def _update_count(self):
        n = sum(1 for v in self.checks.values() if v.get())
        total = len(self.checks)
        self.count_lbl.configure(text=f"已勾 {n} / {total}")

    def _on_confirm(self):
        selected = {c for c, v in self.checks.items() if v.get()}
        total = len(self.checks)
        if not selected:
            if not messagebox.askyesno(
                "確認",
                "目前未勾選任何診所,將不會產出診所相關文件。\n仍要套用嗎?"):
                return
            self.master_app._selected_clinics = set()
        elif len(selected) == total:
            # 全選等於「全部」(預設行為)
            self.master_app._selected_clinics = None
        else:
            self.master_app._selected_clinics = selected
        self.master_app._update_clinic_filter_label()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
