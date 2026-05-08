"""健康台灣深耕計畫 — Word 核銷文件產生器（桌面 GUI 版 v38 — Stepper UI）

v37 → v38 改動範圍：
- UI 全面重做為 Stepper 逐步流程（6 步 + 底部 sticky bar）
- 視覺升級：新色彩體系、字體層級、卡片化、中強度動畫
- 業務邏輯（_on_generate、_do_generate、Gmail 寄送…）完全保留
"""

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

from ui_stepper import (
    StepperHeader, StepperContainer,
    roll_number, animate_height, COLORS,
)


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

# 全域字型
try:
    ctk.ThemeManager.theme["CTkFont"]["family"] = "Microsoft JhengHei UI"
    ctk.ThemeManager.theme["CTkFont"]["size"] = 13
    ctk.ThemeManager.theme["CTkFont"]["weight"] = "normal"
except Exception:
    pass

UI_FONT = "Microsoft JhengHei UI"
MONO_FONT = "Cascadia Mono"


# ──────────────────────────────────────────────────────────
# 6 步定義（label, validator method name）
# ──────────────────────────────────────────────────────────
STEPS = [
    ("匯入", "_validate_step_import"),
    ("申報", "_validate_step_settings"),
    ("文件", "_validate_step_outputs"),
    ("人員", "_validate_step_people"),
    ("分區", "_validate_step_regions"),
    ("輸出", "_validate_step_output"),
]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("⚡ 核銷文件產生器  v40")
        self.geometry("960x780")
        self.minsize(880, 680)
        self.configure(fg_color=COLORS["bg"])

        # 進階篩選：勾選要產生的診所
        self._selected_clinics: set[str] | None = None

        # 產生後狀態
        self._last_month_dir: str | None = None
        self._last_receipt_lookup: dict = {}
        self._last_year: int | None = None
        self._last_month: int | None = None

        # log 展開狀態
        self._log_expanded = False

        # 初始化所有 var
        self._init_vars()

        # 建構 UI
        self._build_ui()

        # 預設顯示第 0 步
        self.stepper_container.show(0)
        self.stepper_header.set_current(0)
        self._update_nav_buttons()

    # ──────────────────────────────────────────────────────
    # 初始化所有變數（從 v37 抽出）
    # ──────────────────────────────────────────────────────
    def _init_vars(self):
        today = date.today()
        roc_year = today.year - 1911

        # Step 1
        self.var_excel = ctk.StringVar()
        self.var_exec_excel = ctk.StringVar()

        # Step 2
        self.var_year = ctk.StringVar(value=str(roc_year))
        self.var_month = ctk.StringVar(value=str(today.month))
        self.var_region = ctk.StringVar(value="全部")
        default_min = str(MIN_PRESCRIPTIONS_DEFAULT)
        self.var_min_by_region: dict[str, ctk.StringVar] = {
            r: ctk.StringVar(value=default_min) for r in regions_mod.REGION_NAMES
        }

        # Step 3 — 10 項勾選
        self.var_gen_doctor_presc_detail = ctk.BooleanVar(value=True)
        self.var_gen_doctor_exec_detail = ctk.BooleanVar(value=True)
        self.var_gen_doctor_receipt = ctk.BooleanVar(value=True)
        self.var_gen_doctor_summary = ctk.BooleanVar(value=True)
        self.var_gen_health_detail = ctk.BooleanVar(value=True)
        self.var_gen_health_receipt = ctk.BooleanVar(value=True)
        self.var_gen_health_summary = ctk.BooleanVar(value=True)
        self.var_gen_treatment_detail = ctk.BooleanVar(value=True)
        self.var_gen_treatment_receipt = ctk.BooleanVar(value=True)
        self.var_gen_treatment_summary = ctk.BooleanVar(value=True)

        # Step 4
        default_db = os.path.join(APP_DIR, "人員個資.xlsx")
        self.var_people_db = ctk.StringVar(value=default_db)

        # Step 5
        default_rg = os.path.join(APP_DIR, "診所分區.xlsx")
        self.var_regions_db = ctk.StringVar(value=default_rg)

        # Step 6
        self.var_output = ctk.StringVar(value=os.path.join(APP_DIR, "核銷文件"))

        # Gmail（不在 stepper 內，但要保留）
        self.var_sender_email = ctk.StringVar()

    # ──────────────────────────────────────────────────────
    # UI 主結構
    # ──────────────────────────────────────────────────────
    def _build_ui(self):
        # ── 頂部 banner ──
        banner = ctk.CTkFrame(
            self, fg_color=COLORS["bg_card"], corner_radius=0,
            height=64,
            border_width=0)
        banner.pack(fill="x", side="top")
        banner.pack_propagate(False)

        binner = ctk.CTkFrame(banner, fg_color="transparent")
        binner.pack(fill="both", expand=True, padx=24, pady=12)

        left = ctk.CTkFrame(binner, fg_color="transparent")
        left.pack(side="left", fill="y")
        ctk.CTkLabel(left, text="⚡  核銷文件產生器",
                     font=ctk.CTkFont(size=30, weight="bold"),
                     text_color=COLORS["accent"]).pack(side="left", anchor="w")
        ctk.CTkLabel(left, text="  v40",
                     font=ctk.CTkFont(family=MONO_FONT, size=12),
                     text_color=COLORS["accent_hi"]).pack(
                         side="left", padx=(6, 0), anchor="s", pady=(0, 4))

        right = ctk.CTkFrame(binner, fg_color="transparent")
        right.pack(side="right", fill="y")
        ctk.CTkLabel(right, text="台北市醫師公會 ◆ 健康台灣深耕計畫",
                     font=ctk.CTkFont(size=17),
                     text_color=COLORS["text_dim"]).pack(side="right",
                                                          anchor="e")

        # 分隔線
        sep = ctk.CTkFrame(self, fg_color=COLORS["border"], height=1)
        sep.pack(fill="x", side="top")

        # ── Stepper Header ──
        header_wrap = ctk.CTkFrame(self, fg_color=COLORS["bg"], height=54)
        header_wrap.pack(fill="x", side="top")
        header_wrap.pack_propagate(False)

        self.stepper_header = StepperHeader(
            header_wrap,
            steps=[s[0] for s in STEPS],
            on_step_click=self._on_header_click,
        )
        self.stepper_header.pack(pady=10)

        # ── Sticky bar（先建，固定底部）──
        self._build_sticky_bar()

        # ── Stepper Container（中間內容，fill=both expand=True）──
        body_wrap = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        body_wrap.pack(fill="both", expand=True, side="top",
                       padx=24, pady=(8, 8))

        self.stepper_container = StepperContainer(body_wrap, n_steps=len(STEPS))
        self.stepper_container.pack(fill="both", expand=True)

        # 建立每一步內容
        self._build_step_import(self.stepper_container.page(0))
        self._build_step_settings(self.stepper_container.page(1))
        self._build_step_outputs(self.stepper_container.page(2))
        self._build_step_people(self.stepper_container.page(3))
        self._build_step_regions(self.stepper_container.page(4))
        self._build_step_output(self.stepper_container.page(5))

    # ──────────────────────────────────────────────────────
    # Sticky Bar（產生進度 + 上一步/下一步/產生/Gmail）
    # ──────────────────────────────────────────────────────
    def _build_sticky_bar(self):
        bar = ctk.CTkFrame(
            self, fg_color=COLORS["bg_card"], corner_radius=0,
            border_width=0, height=128)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        # 上方分隔線
        ctk.CTkFrame(bar, fg_color=COLORS["border"], height=1).pack(fill="x")

        # ── 進度區（產生時顯示） ──
        self.progress_wrap = ctk.CTkFrame(bar, fg_color="transparent")
        # 預設不 pack；產生時才顯示

        prog_row1 = ctk.CTkFrame(self.progress_wrap, fg_color="transparent")
        prog_row1.pack(fill="x", padx=24, pady=(8, 2))

        self.lbl_progress_status = ctk.CTkLabel(
            prog_row1, text="準備中…",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=COLORS["accent"], anchor="w")
        self.lbl_progress_status.pack(side="left")

        self.lbl_progress_pct = ctk.CTkLabel(
            prog_row1, text="0%",
            font=ctk.CTkFont(family=MONO_FONT, size=12, weight="bold"),
            text_color=COLORS["accent"], anchor="e")
        self.lbl_progress_pct.pack(side="right")

        self.progress = ctk.CTkProgressBar(
            self.progress_wrap, height=8,
            progress_color=COLORS["accent"],
            fg_color=COLORS["bg_card_hi"])
        self.progress.pack(fill="x", padx=24, pady=(2, 6))
        self.progress.set(0)
        self._last_progress_pct = 0

        self.lbl_current_file = ctk.CTkLabel(
            self.progress_wrap, text="",
            font=ctk.CTkFont(family=MONO_FONT, size=11),
            text_color=COLORS["text_dim"], anchor="w")
        self.lbl_current_file.pack(fill="x", padx=24, pady=(2, 4))

        # 顯示詳細記錄按鈕
        self.btn_toggle_log = ctk.CTkButton(
            self.progress_wrap, text="顯示詳細記錄 ▼", height=22, width=120,
            fg_color="transparent", hover_color=COLORS["bg_card_hi"],
            text_color=COLORS["text_dim"], border_width=0,
            font=ctk.CTkFont(size=16),
            command=self._toggle_log)
        self.btn_toggle_log.pack(side="left", padx=(20, 0), pady=(0, 4),
                                 anchor="w")

        # ── 隱藏式 log（在 progress_wrap 內，預設高度 0） ──
        self.log_frame = ctk.CTkFrame(
            self.progress_wrap, fg_color=COLORS["bg"],
            height=1, border_width=1, border_color=COLORS["border"])
        # log_frame 預設不 pack，展開時才 pack

        self.log = ctk.CTkTextbox(
            self.log_frame, height=140,
            font=ctk.CTkFont(family=MONO_FONT, size=10),
            fg_color=COLORS["bg"], text_color=COLORS["text_dim"],
            border_width=0)
        self.log.pack(fill="both", expand=True, padx=2, pady=2)

        # ── 按鈕區 ──
        btn_row = ctk.CTkFrame(bar, fg_color="transparent")
        btn_row.pack(fill="x", side="bottom", padx=24, pady=12)

        # 左：上一步
        self.btn_prev = ctk.CTkButton(
            btn_row, text="← 上一步", height=46, width=110,
            fg_color="transparent", hover_color=COLORS["bg_card_hi"],
            text_color=COLORS["text"],
            border_color=COLORS["border"], border_width=1,
            font=ctk.CTkFont(size=18),
            command=self._on_prev)
        self.btn_prev.pack(side="left")

        # 中間：步驟提示
        self.lbl_step_hint = ctk.CTkLabel(
            btn_row, text="",
            font=ctk.CTkFont(size=17),
            text_color=COLORS["text_dim"])
        self.lbl_step_hint.pack(side="left", padx=16)

        # 右：產生文件 / 下一步 / Gmail
        right_btns = ctk.CTkFrame(btn_row, fg_color="transparent")
        right_btns.pack(side="right")

        self.btn_send_email = ctk.CTkButton(
            right_btns, text="📧 預覽並寄送 Gmail", height=46, width=180,
            fg_color=COLORS["success"], hover_color="#15803d",
            text_color="white",
            font=ctk.CTkFont(size=18, weight="bold"),
            command=self._on_open_email_preview)
        self.btn_send_email.pack(side="right", padx=(12, 0))

        # next / generate 兩顆共用同一格，依步驟切換顯示
        # 注意 pack 順序：generate 要在 send_email **左邊**，所以先建立、後 pack（pack right 是堆右側）
        self.btn_next = ctk.CTkButton(
            right_btns, text="下一步 →", height=46, width=130,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hi"],
            text_color="white",
            font=ctk.CTkFont(size=18, weight="bold"),
            command=self._on_next)
        self.btn_next.pack(side="right")

        self.btn_generate = ctk.CTkButton(
            right_btns, text="✨ 產 生 文 件", height=46, width=170,
            fg_color="#16a34a", hover_color="#15803d",
            text_color="white",
            font=ctk.CTkFont(size=19, weight="bold"),
            command=self._on_generate)
        # 預設不 pack；最後一步才出現（pack 在 btn_next 的位置，btn_send_email 的左邊）

    # ──────────────────────────────────────────────────────
    # 共用工具
    # ──────────────────────────────────────────────────────
    def _section_title(self, parent, num, title, subtitle=""):
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="x", pady=(8, 14))

        row = ctk.CTkFrame(wrap, fg_color="transparent")
        row.pack(fill="x")

        # 大數字
        ctk.CTkLabel(
            row, text=str(num),
            font=ctk.CTkFont(family=MONO_FONT, size=42, weight="bold"),
            text_color=COLORS["accent"], width=56
        ).pack(side="left", padx=(0, 14))

        text_col = ctk.CTkFrame(row, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True, anchor="w")
        ctk.CTkLabel(
            text_col, text=title,
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color=COLORS["text"], anchor="w"
        ).pack(fill="x", anchor="w")
        if subtitle:
            ctk.CTkLabel(
                text_col, text=subtitle,
                font=ctk.CTkFont(size=17),
                text_color=COLORS["text_dim"], anchor="w"
            ).pack(fill="x", anchor="w", pady=(2, 0))

    def _card(self, parent, **kw):
        return ctk.CTkFrame(
            parent, fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1, border_color=COLORS["border"],
            **kw,
        )

    def _field_label(self, parent, text):
        return ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=COLORS["text_dim"], anchor="w")

    # ──────────────────────────────────────────────────────
    # Step 1：匯入處方紀錄
    # ──────────────────────────────────────────────────────
    def _build_step_import(self, parent):
        self._section_title(
            parent, "01", "匯入處方紀錄",
            "選擇本月的處方紀錄 Excel —— 開立檔與執行檔分開匯入，方便跨月核銷")

        card = self._card(parent)
        card.pack(fill="x", pady=(0, 12))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=18)

        # 開立
        self._field_label(inner, "開立處方 Excel").pack(fill="x", anchor="w")
        ctk.CTkLabel(
            inner, text="處方費 + 健康管理費",
            font=ctk.CTkFont(size=16),
            text_color=COLORS["text_muted"], anchor="w"
        ).pack(fill="x", anchor="w", pady=(0, 6))

        row1 = ctk.CTkFrame(inner, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 16))
        ctk.CTkEntry(
            row1, textvariable=self.var_excel,
            placeholder_text="尚未選擇檔案…",
            height=46, font=ctk.CTkFont(size=18),
            border_width=1, border_color=COLORS["border"],
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            row1, text="選擇檔案", width=110, height=46,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hi"],
            font=ctk.CTkFont(size=18, weight="bold"),
            command=self._browse_excel
        ).pack(side="right")

        # 執行
        self._field_label(inner, "執行處方 Excel").pack(fill="x", anchor="w")
        ctk.CTkLabel(
            inner, text="處方執行費 + 處方處置費；留空則用開立檔",
            font=ctk.CTkFont(size=16),
            text_color=COLORS["text_muted"], anchor="w"
        ).pack(fill="x", anchor="w", pady=(0, 6))

        row2 = ctk.CTkFrame(inner, fg_color="transparent")
        row2.pack(fill="x")
        ctk.CTkEntry(
            row2, textvariable=self.var_exec_excel,
            placeholder_text="（選填）尚未選擇檔案…",
            height=46, font=ctk.CTkFont(size=18),
            border_width=1, border_color=COLORS["border"],
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            row2, text="選擇檔案", width=110, height=46,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hi"],
            font=ctk.CTkFont(size=18, weight="bold"),
            command=self._browse_exec_excel
        ).pack(side="right")

    # ──────────────────────────────────────────────────────
    # Step 2：申報設定
    # ──────────────────────────────────────────────────────
    def _build_step_settings(self, parent):
        self._section_title(
            parent, "02", "申報設定",
            "設定申報年月、要產出的分區，以及各區健康管理費的最低處方份數門檻")

        card = self._card(parent)
        card.pack(fill="x", pady=(0, 12))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=18)

        # Row 1：年月分區
        row1 = ctk.CTkFrame(inner, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 16))

        col_year = ctk.CTkFrame(row1, fg_color="transparent")
        col_year.pack(side="left", padx=(0, 28))
        self._field_label(col_year, "申報年度（民國）").pack(anchor="w")
        ctk.CTkEntry(
            col_year, textvariable=self.var_year, width=100, height=46,
            font=ctk.CTkFont(family=MONO_FONT, size=14, weight="bold"),
            justify="center",
            border_width=1, border_color=COLORS["border"]
        ).pack(pady=(4, 0))

        col_m = ctk.CTkFrame(row1, fg_color="transparent")
        col_m.pack(side="left", padx=(0, 28))
        self._field_label(col_m, "申報月份").pack(anchor="w")
        ctk.CTkOptionMenu(
            col_m, values=[str(i) for i in range(1, 13)],
            variable=self.var_month, width=100, height=46,
            font=ctk.CTkFont(family=MONO_FONT, size=14, weight="bold"),
            fg_color="#ffffff", text_color=COLORS["text"],
            button_color="#1a1a1a",
            button_hover_color="#404040",
            dropdown_fg_color="#ffffff",
            dropdown_text_color=COLORS["text"],
            dropdown_hover_color="#f0f0ee",
            corner_radius=6,
        ).pack(pady=(4, 0))

        col_r = ctk.CTkFrame(row1, fg_color="transparent")
        col_r.pack(side="left")
        self._field_label(col_r, "分區").pack(anchor="w")
        ctk.CTkOptionMenu(
            col_r, values=["全部"] + list(regions_mod.REGION_NAMES),
            variable=self.var_region, width=130, height=46,
            font=ctk.CTkFont(size=18, weight="bold"),
            fg_color="#ffffff", text_color=COLORS["text"],
            button_color="#1a1a1a",
            button_hover_color="#404040",
            dropdown_fg_color="#ffffff",
            dropdown_text_color=COLORS["text"],
            dropdown_hover_color="#f0f0ee",
            corner_radius=6,
            command=self._on_region_changed,
        ).pack(pady=(4, 0))

        # 分隔
        ctk.CTkFrame(inner, fg_color=COLORS["border"], height=1).pack(
            fill="x", pady=12)

        # Row 2：每區門檻
        ctk.CTkLabel(
            inner, text="健康管理費最低處方份數門檻",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["text"], anchor="w"
        ).pack(fill="x", anchor="w")
        ctk.CTkLabel(
            inner,
            text=f"皆需為 {PEOPLE_DIVISOR} 的倍數（對應人數需為整數）；0 = 不過濾、顯示 X/XX",
            font=ctk.CTkFont(size=16),
            text_color=COLORS["text_muted"], anchor="w"
        ).pack(fill="x", anchor="w", pady=(2, 12))

        row2 = ctk.CTkFrame(inner, fg_color="transparent")
        row2.pack(fill="x")

        self._min_widgets: dict[str, list] = {}
        for r in regions_mod.REGION_NAMES:
            col = ctk.CTkFrame(row2, fg_color="transparent")
            col.pack(side="left", padx=(0, 18))
            lbl = ctk.CTkLabel(
                col, text=r,
                font=ctk.CTkFont(size=17, weight="bold"),
                text_color=COLORS["accent"], anchor="w")
            lbl.pack(anchor="w")
            entry = ctk.CTkEntry(
                col, textvariable=self.var_min_by_region[r],
                width=80, height=46,
                font=ctk.CTkFont(family=MONO_FONT, size=14, weight="bold"),
                justify="center",
                border_width=1, border_color=COLORS["border"])
            entry.pack(pady=(4, 0))
            self._min_widgets[r] = [col, lbl, entry]

    # ──────────────────────────────────────────────────────
    # Step 3：選擇要產生的文件
    # ──────────────────────────────────────────────────────
    def _build_step_outputs(self, parent):
        self._section_title(
            parent, "03", "選擇要產生的文件",
            "三大群組共 10 項，勾選 = 該資料夾才會產出。點「詳情」可微調每一項")

        # 三大群組設定
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
        self._gen_group_detail_frames: dict = {}
        self._gen_group_detail_buttons: dict = {}
        self._gen_group_detail_open: dict = {}
        self._suppress_group_sync = False

        for g in self._gen_groups:
            card = self._card(parent)
            card.pack(fill="x", pady=(0, 10))

            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=14)

            main_var = ctk.BooleanVar(value=True)
            self._gen_group_main_vars[g["key"]] = main_var

            chk = ctk.CTkCheckBox(
                row, text=g["title"], variable=main_var,
                font=ctk.CTkFont(size=19, weight="bold"),
                text_color=COLORS["text"],
                fg_color=COLORS["accent"], hover_color=COLORS["accent_hi"],
                border_color=COLORS["border"], border_width=2,
                checkmark_color="#ffffff",
                checkbox_width=22, checkbox_height=22,
                command=lambda gk=g["key"]: self._on_group_main_clicked(gk))
            chk.pack(side="left")

            status_lbl = ctk.CTkLabel(
                row, text="",
                text_color=COLORS["text_dim"],
                font=ctk.CTkFont(size=16))
            status_lbl.pack(side="left", padx=(15, 0))
            self._gen_group_status_lbls[g["key"]] = status_lbl

            btn_detail = ctk.CTkButton(
                row, text="詳情 ▼", width=90, height=32,
                fg_color="transparent",
                hover_color=COLORS["bg_card_hi"],
                text_color=COLORS["accent"],
                border_color=COLORS["accent"],
                border_width=1,
                font=ctk.CTkFont(size=17, weight="bold"),
                command=lambda gk=g["key"]: self._toggle_group_detail(gk))
            btn_detail.pack(side="right")
            self._gen_group_detail_buttons[g["key"]] = btn_detail

            # ── inline 展開區（預設隱藏） ──
            detail = ctk.CTkFrame(card, fg_color="transparent")
            inner_d = ctk.CTkFrame(
                detail, fg_color=COLORS["bg"],
                corner_radius=8,
                border_width=1, border_color=COLORS["border"])
            inner_d.pack(fill="x", padx=18, pady=(0, 14))

            # 全選 / 全不選
            tool_row = ctk.CTkFrame(inner_d, fg_color="transparent")
            tool_row.pack(fill="x", padx=14, pady=(12, 6))
            ctk.CTkLabel(
                tool_row,
                text="勾選 = 該資料夾才會產出。每個資料夾獨立控制。",
                font=ctk.CTkFont(size=16),
                text_color=COLORS["text_dim"]
            ).pack(side="left")
            ctk.CTkButton(
                tool_row, text="✓ 全選", width=70, height=28,
                fg_color=COLORS["text"], hover_color="#000",
                text_color="#fff",
                font=ctk.CTkFont(size=16, weight="bold"),
                command=lambda gk=g["key"]: self._set_group_all(gk, True)
            ).pack(side="right", padx=(6, 0))
            ctk.CTkButton(
                tool_row, text="✕ 全不選", width=80, height=28,
                fg_color="transparent", hover_color=COLORS["bg_card_hi"],
                text_color=COLORS["text"],
                border_color=COLORS["border"], border_width=1,
                font=ctk.CTkFont(size=16),
                command=lambda gk=g["key"]: self._set_group_all(gk, False)
            ).pack(side="right")

            # 子項列表
            for sub_var, folder_name, desc in g["items"]:
                item_card = ctk.CTkFrame(
                    inner_d, fg_color=COLORS["bg_card"],
                    corner_radius=6,
                    border_width=1, border_color=COLORS["border"])
                item_card.pack(fill="x", padx=14, pady=(0, 8))

                irow = ctk.CTkFrame(item_card, fg_color="transparent")
                irow.pack(fill="x", padx=12, pady=10)

                ctk.CTkCheckBox(
                    irow, text="", variable=sub_var, width=22,
                    fg_color=COLORS["accent"],
                    hover_color=COLORS["accent_hi"],
                    border_color=COLORS["border"], border_width=2,
                    checkmark_color="#fff",
                    checkbox_width=20, checkbox_height=20
                ).pack(side="left", padx=(0, 10))

                tcol = ctk.CTkFrame(irow, fg_color="transparent")
                tcol.pack(side="left", fill="x", expand=True)
                ctk.CTkLabel(
                    tcol, text=f"📁  {folder_name}",
                    font=ctk.CTkFont(size=17, weight="bold"),
                    text_color=COLORS["text"], anchor="w"
                ).pack(fill="x", anchor="w")
                ctk.CTkLabel(
                    tcol, text=desc,
                    font=ctk.CTkFont(size=16),
                    text_color=COLORS["text_dim"], anchor="w"
                ).pack(fill="x", anchor="w", pady=(2, 0))

            # 留隱藏狀態
            self._gen_group_detail_frames[g["key"]] = detail
            self._gen_group_detail_open[g["key"]] = False
            # detail 不 pack；toggle 時 pack/unpack

            for sub_var, _, _ in g["items"]:
                sub_var.trace_add(
                    "write",
                    lambda *a, gk=g["key"]: self._update_group_status(gk))
            self._update_group_status(g["key"])

    # ──────────────────────────────────────────────────────
    # Step 4：人員個資
    # ──────────────────────────────────────────────────────
    def _build_step_people(self, parent):
        self._section_title(
            parent, "04", "人員個資（選填）",
            "醫師、診所、課程老師的姓名、身分證、地址、電話、銀行資訊。可從舊領據自動匯入")

        card = self._card(parent)
        card.pack(fill="x", pady=(0, 12))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=18)

        self._field_label(inner, "個資 Excel 路徑").pack(fill="x", anchor="w")
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x", pady=(6, 14))
        ctk.CTkEntry(
            row, textvariable=self.var_people_db,
            height=46, font=ctk.CTkFont(size=18)
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            row, text="選擇檔案", width=110, height=46,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hi"],
            font=ctk.CTkFont(size=18, weight="bold"),
            command=self._browse_people_db
        ).pack(side="right")

        # 操作鈕
        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(fill="x")
        ctk.CTkButton(
            btns, text="建立空白範本", width=120, height=48,
            fg_color="transparent", hover_color=COLORS["bg_card_hi"],
            text_color=COLORS["text"],
            border_color=COLORS["border"], border_width=1,
            font=ctk.CTkFont(size=17),
            command=self._create_people_db_template
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            btns, text="開啟編輯", width=100, height=48,
            fg_color="transparent", hover_color=COLORS["bg_card_hi"],
            text_color=COLORS["text"],
            border_color=COLORS["border"], border_width=1,
            font=ctk.CTkFont(size=17),
            command=self._open_people_db
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            btns, text="📥 從舊領據匯入", width=140, height=48,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hi"],
            font=ctk.CTkFont(size=17, weight="bold"),
            command=self._import_from_receipts
        ).pack(side="left")

        ctk.CTkLabel(
            inner,
            text="ℹ 每人一行：姓名、身分證、戶籍地址、聯絡電話、戶名、銀行及分行、銀行代碼、帳號",
            font=ctk.CTkFont(size=16),
            text_color=COLORS["text_muted"], anchor="w", justify="left"
        ).pack(fill="x", anchor="w", pady=(14, 0))

    # ──────────────────────────────────────────────────────
    # Step 5：診所分區
    # ──────────────────────────────────────────────────────
    def _build_step_regions(self, parent):
        self._section_title(
            parent, "05", "診所分區",
            "Excel 三分頁：北投／士林／中山。可進階勾選只產出特定診所")

        card = self._card(parent)
        card.pack(fill="x", pady=(0, 12))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=18)

        self._field_label(inner, "分區 Excel 路徑").pack(fill="x", anchor="w")
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x", pady=(6, 14))
        ctk.CTkEntry(
            row, textvariable=self.var_regions_db,
            height=46, font=ctk.CTkFont(size=18)
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            row, text="選擇檔案", width=110, height=46,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hi"],
            font=ctk.CTkFont(size=18, weight="bold"),
            command=self._browse_regions
        ).pack(side="right")

        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(fill="x", pady=(0, 14))
        ctk.CTkButton(
            btns, text="建立空白範本", width=120, height=48,
            fg_color="transparent", hover_color=COLORS["bg_card_hi"],
            text_color=COLORS["text"],
            border_color=COLORS["border"], border_width=1,
            font=ctk.CTkFont(size=17),
            command=self._create_regions_template
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            btns, text="開啟編輯", width=100, height=48,
            fg_color="transparent", hover_color=COLORS["bg_card_hi"],
            text_color=COLORS["text"],
            border_color=COLORS["border"], border_width=1,
            font=ctk.CTkFont(size=17),
            command=self._open_regions
        ).pack(side="left")

        # 進階篩選
        ctk.CTkFrame(inner, fg_color=COLORS["border"], height=1).pack(
            fill="x", pady=4)

        ctk.CTkLabel(
            inner, text="進階：選擇要產生的診所",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["text"], anchor="w"
        ).pack(fill="x", anchor="w", pady=(12, 4))

        adv_row = ctk.CTkFrame(inner, fg_color="transparent")
        adv_row.pack(fill="x")
        ctk.CTkButton(
            adv_row, text="📋 勾選診所", width=130, height=46,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hi"],
            font=ctk.CTkFont(size=17, weight="bold"),
            command=self._open_clinic_selector
        ).pack(side="left")

        self.lbl_clinic_filter = ctk.CTkLabel(
            adv_row, text="目前：全部診所（預設）",
            text_color=COLORS["text_dim"],
            font=ctk.CTkFont(size=17), anchor="w")
        self.lbl_clinic_filter.pack(side="left", padx=12, fill="x", expand=True)

        ctk.CTkButton(
            adv_row, text="重設", width=70, height=32,
            fg_color="transparent", hover_color=COLORS["bg_card_hi"],
            text_color=COLORS["text_dim"],
            border_color=COLORS["border"], border_width=1,
            font=ctk.CTkFont(size=16),
            command=self._reset_clinic_filter
        ).pack(side="right")

    # ──────────────────────────────────────────────────────
    # Step 6：輸出位置 + Gmail
    # ──────────────────────────────────────────────────────
    def _build_step_output(self, parent):
        self._section_title(
            parent, "06", "輸出位置 & 寄送設定",
            "選擇文件輸出資料夾。Gmail 為選填，可在產生後從底部按鈕寄送")

        # 輸出位置
        card1 = self._card(parent)
        card1.pack(fill="x", pady=(0, 12))
        inner1 = ctk.CTkFrame(card1, fg_color="transparent")
        inner1.pack(fill="x", padx=20, pady=18)

        self._field_label(inner1, "輸出資料夾").pack(fill="x", anchor="w")
        row1 = ctk.CTkFrame(inner1, fg_color="transparent")
        row1.pack(fill="x", pady=(6, 0))
        ctk.CTkEntry(
            row1, textvariable=self.var_output,
            height=46, font=ctk.CTkFont(size=18)
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            row1, text="選擇資料夾", width=110, height=46,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hi"],
            font=ctk.CTkFont(size=18, weight="bold"),
            command=self._browse_output
        ).pack(side="right")

        # Gmail
        card2 = self._card(parent)
        card2.pack(fill="x", pady=(0, 12))
        inner2 = ctk.CTkFrame(card2, fg_color="transparent")
        inner2.pack(fill="x", padx=20, pady=18)

        self._field_label(inner2, "📧 Gmail 寄送設定（選填）").pack(
            fill="x", anchor="w")
        ctk.CTkLabel(
            inner2,
            text="App Password 會在按下底部「📧 預覽並寄送 Gmail」時輸入",
            font=ctk.CTkFont(size=16),
            text_color=COLORS["text_muted"], anchor="w"
        ).pack(fill="x", anchor="w", pady=(0, 6))

        ctk.CTkEntry(
            inner2, textvariable=self.var_sender_email,
            placeholder_text="your-name@gmail.com",
            height=46, font=ctk.CTkFont(size=18)
        ).pack(fill="x", pady=(2, 0))

        # 「按下下面的『產生文件』」提示
        hint = ctk.CTkLabel(
            parent,
            text="✨ 設定完成！按右下角「產 生 文 件」開始批次處理",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["accent"]
        )
        hint.pack(pady=12)

    # ──────────────────────────────────────────────────────
    # Stepper 導覽
    # ──────────────────────────────────────────────────────
    def _on_header_click(self, idx: int):
        cur = self.stepper_container.current()
        if idx == cur:
            return
        if idx > cur:
            # 往前要逐步驗證
            for i in range(cur, idx):
                if not self._validate_step(i):
                    return
        self._goto(idx)

    def _on_prev(self):
        cur = self.stepper_container.current()
        if cur > 0:
            self._goto(cur - 1)

    def _on_next(self):
        cur = self.stepper_container.current()
        if not self._validate_step(cur):
            return
        if cur < len(STEPS) - 1:
            self._goto(cur + 1)

    def _goto(self, idx: int):
        cur = self.stepper_container.current()
        direction = "forward" if idx > cur else "backward"
        self.stepper_container.go(idx, direction=direction)
        self.stepper_header.set_current(idx)
        self._update_nav_buttons(idx)
        # Step 2 切到時觸發分區欄位顯示
        if idx == 1:
            self.after(50, self._on_region_changed)

    def _update_nav_buttons(self, idx: int = None):
        if idx is None:
            cur = self.stepper_container.current()
        else:
            cur = idx
        total = len(STEPS)

        # 上一步
        if cur == 0:
            self.btn_prev.configure(state="disabled")
        else:
            self.btn_prev.configure(state="normal")

        # 下一步 / 產生文件（pack 在 send_email 左邊）
        if cur == total - 1:
            self.btn_next.pack_forget()
            try:
                self.btn_generate.pack(
                    side="right", before=self.btn_send_email)
            except Exception:
                self.btn_generate.pack(side="right")
        else:
            self.btn_generate.pack_forget()
            try:
                self.btn_next.pack(
                    side="right", before=self.btn_send_email)
            except Exception:
                self.btn_next.pack(side="right")

        # 中間提示
        self.lbl_step_hint.configure(
            text=f"步驟 {cur + 1} / {total} · {STEPS[cur][0]}")

    # ──────────────────────────────────────────────────────
    # 每步驗證
    # ──────────────────────────────────────────────────────
    def _validate_step(self, idx: int) -> bool:
        method_name = STEPS[idx][1]
        method = getattr(self, method_name, None)
        if method:
            return method()
        return True

    def _validate_step_import(self) -> bool:
        excel = self.var_excel.get().strip()
        if not excel:
            messagebox.showerror("缺少檔案", "請先選擇「開立處方 Excel」")
            return False
        if not os.path.exists(excel):
            messagebox.showerror(
                "檔案不存在", f"找不到開立處方 Excel：\n{excel}")
            return False
        exec_path = self.var_exec_excel.get().strip()
        if exec_path and not os.path.exists(exec_path):
            messagebox.showerror(
                "檔案不存在", f"找不到執行處方 Excel：\n{exec_path}")
            return False
        return True

    def _validate_step_settings(self) -> bool:
        try:
            int(self.var_year.get())
            int(self.var_month.get())
        except (ValueError, TypeError):
            messagebox.showerror("錯誤", "申報年度/月份必須是數字")
            return False
        try:
            self._region_thresholds()
        except ValueError as e:
            messagebox.showerror("錯誤", str(e))
            return False
        return True

    def _validate_step_outputs(self) -> bool:
        any_on = any([
            self.var_gen_doctor_presc_detail.get(),
            self.var_gen_doctor_exec_detail.get(),
            self.var_gen_doctor_receipt.get(),
            self.var_gen_doctor_summary.get(),
            self.var_gen_health_detail.get(),
            self.var_gen_health_receipt.get(),
            self.var_gen_health_summary.get(),
            self.var_gen_treatment_detail.get(),
            self.var_gen_treatment_receipt.get(),
            self.var_gen_treatment_summary.get(),
        ])
        if not any_on:
            messagebox.showerror(
                "未選任何文件",
                "10 項都未勾選，產生文件不會有任何輸出。\n"
                "請至少勾選一項。")
            return False
        return True

    def _validate_step_people(self) -> bool:
        # 選填，不擋
        return True

    def _validate_step_regions(self) -> bool:
        # 選填，不擋
        return True

    def _validate_step_output(self) -> bool:
        out = self.var_output.get().strip()
        if not out:
            messagebox.showerror("缺少輸出位置", "請選擇輸出資料夾")
            return False
        return True

    # ──────────────────────────────────────────────────────
    # 詳細記錄展開／收起
    # ──────────────────────────────────────────────────────
    def _toggle_log(self):
        if self._log_expanded:
            self.log_frame.pack_forget()
            self.btn_toggle_log.configure(text="顯示詳細記錄 ▼")
            self._log_expanded = False
        else:
            self.log_frame.pack(fill="x", padx=24, pady=(0, 4))
            self.btn_toggle_log.configure(text="隱藏詳細記錄 ▲")
            self._log_expanded = True

    def _show_progress_panel(self):
        self.progress_wrap.pack(fill="x", side="top",
                                before=self.btn_prev.master)
        # progress_wrap 要在 btn_row 之上：直接重 pack
        self.progress_wrap.pack(fill="x", side="top")
        # 由於 sticky bar 已經 pack_propagate(False)、高度固定，
        # 為了顯示 progress + log，動態調整 bar 高度
        bar = self.progress_wrap.master
        bar.configure(height=180 if not self._log_expanded else 340)

    def _hide_progress_panel(self):
        self.progress_wrap.pack_forget()
        bar = self.progress.master.master  # progress_wrap → bar
        bar.configure(height=72)

    # ──────────────────────────────────────────────────────
    # ↓↓↓ 以下為 v37 原生邏輯，完全保留，不做改動 ↓↓↓
    # ──────────────────────────────────────────────────────
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
        try:
            import win32com.client
            pdf_path = docx_path.replace(".docx", ".pdf")
            word = win32com.client.DispatchEx("Word.Application")
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

    def _on_region_changed(self, *_):
        choice = self.var_region.get()
        if not hasattr(self, "_min_widgets"):
            return
        for r, widgets in self._min_widgets.items():
            show = (choice == "全部" or choice == r)
            col = widgets[0]
            if show:
                col.pack(side="left", padx=(0, 18))
            else:
                col.pack_forget()

    def _browse_regions(self):
        path = filedialog.askopenfilename(
            title="選擇診所分區 Excel",
            filetypes=[("Excel 檔案", "*.xlsx"), ("所有檔案", "*.*")])
        if path:
            self.var_regions_db.set(path)
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

    def _open_clinic_selector(self):
        regions_path = self.var_regions_db.get().strip()
        regions_map = regions_mod.load_regions(regions_path)
        if not regions_map or not any(regions_map.values()):
            messagebox.showwarning(
                "找不到診所清單",
                "診所分區檔不存在或為空白,請先設定。")
            return
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
                text="目前：全部診所（預設）",
                text_color=COLORS["text_dim"])
        elif not sel:
            self.lbl_clinic_filter.configure(
                text="目前：未勾選任何診所（不會產出）",
                text_color=COLORS["danger"])
        else:
            n = len(sel)
            preview = ", ".join(list(sel)[:3])
            if n > 3:
                preview += f" 等 {n} 間"
            else:
                preview = f"已選 {n} 間：{preview}"
            self.lbl_clinic_filter.configure(
                text=f"目前：{preview}",
                text_color=COLORS["accent"])

    def _reset_clinic_filter(self):
        self._selected_clinics = None
        self._update_clinic_filter_label()

    def _get_group(self, group_key: str):
        for g in self._gen_groups:
            if g["key"] == group_key:
                return g
        raise KeyError(group_key)

    def _on_group_main_clicked(self, group_key: str):
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
        if self._suppress_group_sync:
            return
        g = self._get_group(group_key)
        n = sum(1 for sub_var, _, _ in g["items"] if sub_var.get())
        total = len(g["items"])
        lbl = self._gen_group_status_lbls[group_key]
        main_var = self._gen_group_main_vars[group_key]

        if n == total:
            if not main_var.get():
                main_var.set(True)
            lbl.configure(text=f"{total}/{total} 項全部產出",
                          text_color=COLORS["success"])
        elif n == 0:
            if main_var.get():
                main_var.set(False)
            lbl.configure(text="整組不產出", text_color=COLORS["danger"])
        else:
            if main_var.get():
                main_var.set(False)
            lbl.configure(text=f"部分產出 ({n}/{total} 項)",
                          text_color=COLORS["warn"])

    def _open_group_detail(self, group_key: str):
        # 保留舊 API 名稱（外部有人呼叫到 fallback）
        self._toggle_group_detail(group_key)

    def _toggle_group_detail(self, group_key: str):
        detail = self._gen_group_detail_frames.get(group_key)
        btn = self._gen_group_detail_buttons.get(group_key)
        if not detail:
            return
        is_open = self._gen_group_detail_open.get(group_key, False)
        if is_open:
            detail.pack_forget()
            self._gen_group_detail_open[group_key] = False
            if btn:
                btn.configure(text="詳情 ▼")
        else:
            detail.pack(fill="x")
            self._gen_group_detail_open[group_key] = True
            if btn:
                btn.configure(text="收合 ▲")

    def _set_group_all(self, group_key: str, value: bool):
        g = self._get_group(group_key)
        if not g:
            return
        self._suppress_group_sync = True
        for sub_var, _, _ in g["items"]:
            sub_var.set(value)
        self._suppress_group_sync = False
        main_var = self._gen_group_main_vars.get(group_key)
        if main_var:
            main_var.set(value)
        self._update_group_status(group_key)

    @staticmethod
    def _clinic_matches_selection(institution: str, selected: set[str]) -> bool:
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
        REQUIRED_FIELDS = [
            ("id_number",      "身分證字號"),
            ("address",        "戶籍地址"),
            ("phone",          "聯絡電話"),
            ("account_name",   "戶名"),
            ("bank_branch",    "銀行及分行"),
            ("bank_code",      "銀行代碼"),
            ("account_number", "帳號"),
        ]

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

        try:
            self._region_thresholds_cache = self._region_thresholds()
        except ValueError as e:
            messagebox.showerror("錯誤", str(e))
            return

        self.btn_generate.configure(state="disabled", text="產生中…")
        self.btn_prev.configure(state="disabled")

        # 顯示 progress 區
        self._show_progress_panel()
        self.log.delete("1.0", "end")
        self.progress.set(0)
        self._last_progress_pct = 0
        self.lbl_progress_pct.configure(text="0%")
        self.lbl_progress_status.configure(text="準備中…",
                                           text_color=COLORS["accent"])
        self.lbl_current_file.configure(text="")

        threading.Thread(target=self._generate_worker, daemon=True).start()

    def _generate_worker(self):
        try:
            self._do_generate()
        except Exception as e:
            self.after(0, lambda: self._log(f"\n錯誤：{e}"))
            self.after(0, lambda: messagebox.showerror("錯誤", str(e)))
            self.after(0, lambda: self.lbl_progress_status.configure(
                text="發生錯誤", text_color=COLORS["danger"]))
        finally:
            self.after(0, lambda: self.btn_generate.configure(
                state="normal", text="✨ 產 生 文 件"))
            self.after(0, lambda: self.btn_prev.configure(state="normal"))

    def _set_progress(self, pct: float, status: str = None,
                      current_file: str = None):
        """thread-safe：UI 更新請用 self.after 包"""
        self.progress.set(pct)
        new_pct = int(pct * 100)
        try:
            roll_number(self.lbl_progress_pct,
                        self._last_progress_pct, new_pct, "{}%", 200)
            self._last_progress_pct = new_pct
        except Exception:
            self.lbl_progress_pct.configure(text=f"{new_pct}%")
        if status:
            self.lbl_progress_status.configure(text=status)
        if current_file is not None:
            # 截短超長檔名
            disp = current_file
            if len(disp) > 60:
                disp = "…" + disp[-58:]
            self.lbl_current_file.configure(text=disp)

    def _filter_data(self, data, allowed_clinics: set[str]):
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
        return [r for r in raw_records
                if len(r) > 7 and str(r[7] or "") in allowed_clinics]

    def _produce_for_scope(
        self, scope_label, data,
        raw_records_issuance, raw_records_execution,
        month_dir, prefix, min_presc,
        receipt_lookup, produce_executor, step_cb,
    ):
        os.makedirs(month_dir, exist_ok=True)

        def subdir(name):
            d = os.path.join(month_dir, name)
            os.makedirs(d, exist_ok=True)
            return d

        OTHER_DIR = "其他內容"

        def agg_subdir(name):
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

        if self.var_gen_doctor_summary.get() and data.doctors:
            d = agg_subdir(COMBINED_DIR_NAME)
            try:
                generate_prescription_fee_excel(raw_records_issuance, prefix, d)
                generate_execution_fee_excel(raw_records_execution, prefix, d)
            except Exception:
                pass
            path1 = os.path.join(d, f"健康台灣深耕計畫_處方費-總表-{prefix}.docx")
            tmpl1 = DEFAULT_TEMPLATES["prescription"]
            if os.path.exists(tmpl1):
                generate_prescription_fee_from_template(tmpl1, data, path1)
            else:
                generate_prescription_fee_doc(data, path1)
            all_pending_docx.append(os.path.abspath(path1))
            path2 = os.path.join(d, f"健康台灣深耕計畫_處方執行費核銷總表-{prefix}.docx")
            tmpl2 = DEFAULT_TEMPLATES["execution"]
            if os.path.exists(tmpl2):
                generate_execution_fee_from_template(tmpl2, data, path2)
            else:
                generate_execution_fee_doc(data, path2)
            all_pending_docx.append(os.path.abspath(path2))
            self.after(0, lambda s=scope_label: self._log(
                f"[{s}] 處方費、處方執行費總表明細表合併檔與Excel"))
            step_cb()

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
            self.after(0, lambda s=scope_label, c=count, p="、".join(parts):
                       self._log(f"[{s}] {p} ({c} 位醫師)"))
            step_cb()

        if self.var_gen_health_summary.get() and data.health_mgmts:
            d = agg_subdir(HEALTH_COMBINED_DIR)
            try:
                generate_health_mgmt_excel(raw_records_issuance, prefix, d)
            except Exception:
                pass
            path = os.path.join(d, f"健康台灣深耕計畫_健康管理費總表-{prefix}.docx")
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
            self.after(0, lambda s=scope_label, x=len(xlsx_paths):
                       self._log(
                f"[{s}] 健康管理費合併總表與個人excel (個別Excel×{x})"))
            step_cb()

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

        if produce_executor and self.var_gen_treatment_summary.get() \
                and data.executors:
            d = agg_subdir(TREATMENT_COMBINED_DIR)
            p1 = os.path.join(d, f"健康台灣深耕計畫_處方處置費核銷總表-{prefix}.docx")
            generate_treatment_fee_doc(data, p1)
            p2 = os.path.join(d, f"健康台灣深耕計畫_執行人員民眾明細表-{prefix}.docx")
            generate_executor_patient_list_doc(data, p2)
            self.after(0, lambda s=scope_label: self._log(
                f"[{s}] 處方處置費合併總表word"))
            step_cb()

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
            count = len({ex.executor_name for ex in data.executors
                         if ex.receipt and ex.receipt.amount > 0})
            parts = []
            if emit_td:
                parts.append("處方處置費民眾明細")
            if emit_tr:
                parts.append("處方處置費領據")
            self.after(0, lambda s=scope_label, c=count, p="、".join(parts):
                       self._log(f"[{s}] {p} ({c} 位老師)"))
            step_cb()

        return (all_pending_docx, health_merge_info,
                executor_merge_info, doctor_merge_info)

    def _do_generate(self):
        issuance_excel = self.var_excel.get().strip()
        execution_excel = self.var_exec_excel.get().strip()
        if not execution_excel:
            execution_excel = issuance_excel
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
        self.after(0, lambda: self._set_progress(
            0.05, "讀取 Excel…", os.path.basename(issuance_excel)))

        data = read_prescription_report(
            issuance_excel,
            execution_path=execution_excel,
            report_year=year, report_month=month,
            min_prescriptions=0,
        )
        raw_records_issuance = read_raw_records(issuance_excel)
        if execution_excel != issuance_excel:
            raw_records_execution = read_raw_records(execution_excel)
        else:
            raw_records_execution = raw_records_issuance

        self.after(0, lambda: self._log(
            f"  醫師: {len(data.doctors)} 位 | "
            f"診所: {len(data.health_mgmts)} 間 | "
            f"執行人員: {len({ex.executor_name for ex in data.executors})} 位\n"
        ))

        receipt_lookup = {}
        db_path = self.var_people_db.get().strip()
        if db_path and os.path.exists(db_path):
            self.after(0, lambda: self._log("讀取人員個資檔..."))
            receipt_lookup = load_people_db(db_path)

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

        regions_path = self.var_regions_db.get().strip()
        regions_map = regions_mod.load_regions(regions_path)
        if not regions_map or not any(regions_map.values()):
            self.after(0, lambda: self._log(
                "⚠ 無分區名單(檔案不存在或空白),全部診所會歸為「其他」"))

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

        prefix = f"{year}年{month:02d}月"
        month_dir_root = os.path.join(output, prefix)
        os.makedirs(month_dir_root, exist_ok=True)

        scopes: list[tuple[str, set[str], int, str, bool]] = []
        if region_choice == "全部":
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
                True))

        self.after(0, lambda: self._log(
            f"\n產生範圍:{len(scopes)} 個 scope"))

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
        clinic_scope_count = sum(1 for _, allowed, _, _, _ in scopes if allowed)
        executor_scope_count = sum(1 for _, _, _, _, pe in scopes if pe)
        total_steps = (per_scope_steps * clinic_scope_count
                       + executor_steps_per * executor_scope_count)
        if total_steps == 0:
            total_steps = 1

        steps_done = 0

        self.after(0, lambda: self._set_progress(
            0.1, "Step 1/2 · 產生 Word 文件中…"))

        def step_cb():
            nonlocal steps_done
            steps_done += 1
            pct = 0.1 + 0.6 * steps_done / total_steps
            self.after(0, lambda p=pct, d=steps_done, t=total_steps:
                       self._set_progress(
                           p, f"Step 1/2 · 產生 Word 文件 {d}/{t}"))

        all_pending_docx: list[str] = []
        merge_bundles: list[tuple] = []

        for i, (scope_label, allowed, threshold, month_dir,
                produce_exec) in enumerate(scopes):
            data_scope = self._filter_data(data, allowed)
            raw_scope_issuance = self._filter_raw_records(
                raw_records_issuance, allowed)
            raw_scope_execution = self._filter_raw_records(
                raw_records_execution, allowed)

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

        if all_pending_docx:
            total_pdf = len(all_pending_docx)
            self.after(0, lambda: self._log(
                f"\n批次轉換 {total_pdf} 份 Word → PDF…"))
            self.after(0, lambda: self._set_progress(
                0.7, "Step 2/2 · Word → PDF 轉檔中…"))

            def _pdf_progress(done, total, name):
                in_name = os.path.basename(name) if name else ""
                pct = 0.7 + 0.28 * done / total
                self.after(0, lambda p=pct, n=in_name, d=done, t=total:
                           self._set_progress(
                               p, f"Step 2/2 · PDF 轉檔 {d}/{t}", n))
                if done % 10 == 0 or done == total:
                    self.after(0, lambda d=done, t=total, n=name:
                               self._log(f"  [{d}/{t}] {n}"))
            _convert_docx_list_to_pdf(all_pending_docx, progress_cb=_pdf_progress)
            self.after(0, lambda: self._log(
                f"[OK] {total_pdf} 份 PDF 轉換完成"))

        for health_merge_info, executor_merge_info, doctor_merge_info in merge_bundles:
            if health_merge_info:
                merge_health_mgmt_pdfs(*health_merge_info)
            if executor_merge_info:
                merge_executor_pdfs(*executor_merge_info)
            if doctor_merge_info:
                merge_doctor_receipt_pdfs(doctor_merge_info)

        self._log_incomplete_recipients(data, receipt_lookup)

        month_dir = month_dir_root

        self.after(0, lambda: self._set_progress(
            1.0, "✓ 全部完成", ""))
        self.after(0, lambda: self.lbl_progress_status.configure(
            text="✓ 全部完成", text_color=COLORS["success"]))
        self.after(0, lambda: self._log(
            f"\n完成！共產生至: {output}"))

        self._last_month_dir = month_dir
        self._last_receipt_lookup = receipt_lookup
        self._last_year = year
        self._last_month = month

        self.after(0, lambda: messagebox.showinfo(
            "完成", f"所有文件已產生！\n\n輸出至: {output}\n\n如需寄送，請按「📧 預覽並寄送 Gmail」。"))
        self.after(0, lambda: os.startfile(output))

    def _on_open_email_preview(self):
        sender = self.var_sender_email.get().strip()
        if not sender:
            messagebox.showwarning(
                "缺少寄件者",
                "請在第 6 步「輸出位置 & 寄送設定」填入寄件 Gmail。")
            return
        if "@" not in sender:
            messagebox.showwarning("Email 格式錯誤", "寄件 Gmail 看起來不對，請確認。")
            return

        try:
            year = int(self.var_year.get())
            month = int(self.var_month.get())
        except (ValueError, TypeError):
            messagebox.showerror("錯誤", "申報年度/月份必須是數字")
            return

        output = self.var_output.get().strip()
        if not output:
            messagebox.showwarning("缺少輸出位置", "請先指定輸出資料夾。")
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
# 群組詳情 / 診所選擇器（v37 沿用，配色微調）
# ──────────────────────────────────────────────────────────
class GroupDetailWindow(ctk.CTkToplevel):
    def __init__(self, master, group: dict):
        super().__init__(master)
        self.title(f"產出細項 — {group['title']}")
        self.geometry("720x520")
        self.minsize(580, 380)
        self.configure(fg_color=COLORS["bg"])

        self.group = group
        self._build_ui()
        self.transient(master)
        self.after(100, self.lift)
        self.after(150, self.focus_force)

    def _build_ui(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=22, pady=(22, 4))
        ctk.CTkLabel(top, text="◢ " + self.group["title"],
                     font=ctk.CTkFont(size=23, weight="bold"),
                     text_color=COLORS["accent"]).pack(side="left")

        ctk.CTkLabel(
            self,
            text="勾選 = 該資料夾才會產出。每個資料夾獨立控制。",
            text_color=COLORS["text_dim"], font=ctk.CTkFont(size=16),
            anchor="w").pack(fill="x", padx=22, pady=(0, 8))

        ops = ctk.CTkFrame(self, fg_color="transparent")
        ops.pack(fill="x", padx=22, pady=(0, 10))
        ctk.CTkButton(ops, text="✓ 全選", width=80, height=30,
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hi"],
                      font=ctk.CTkFont(size=17),
                      command=self._select_all).pack(side="left", padx=(0, 6))
        ctk.CTkButton(ops, text="✕ 全不選", width=80, height=30,
                      fg_color="transparent",
                      hover_color=COLORS["bg_card_hi"],
                      text_color=COLORS["text"],
                      border_color=COLORS["border"], border_width=1,
                      font=ctk.CTkFont(size=17),
                      command=self._select_none).pack(side="left")

        scroll = ctk.CTkScrollableFrame(
            self, fg_color=COLORS["bg_card"])
        scroll.pack(fill="both", expand=True, padx=22, pady=(0, 12))

        for sub_var, folder, desc in self.group["items"]:
            row = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card_hi"],
                               corner_radius=8, border_width=1,
                               border_color=COLORS["border"])
            row.pack(fill="x", pady=5, padx=2)

            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=10)

            ctk.CTkCheckBox(inner, text="", variable=sub_var,
                            width=22, checkbox_width=20,
                            checkbox_height=20,
                            fg_color=COLORS["accent"],
                            hover_color=COLORS["accent_hi"],
                            border_color=COLORS["border"], border_width=2,
                            checkmark_color="#ffffff").pack(
                                side="left", padx=(0, 12))

            text_frame = ctk.CTkFrame(inner, fg_color="transparent")
            text_frame.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(
                text_frame, text="📁  " + folder,
                font=ctk.CTkFont(family=MONO_FONT, size=13, weight="bold"),
                text_color=COLORS["accent"], anchor="w").pack(fill="x")
            ctk.CTkLabel(
                text_frame, text="    " + desc,
                font=ctk.CTkFont(size=16),
                text_color=COLORS["text_dim"], anchor="w").pack(fill="x")

        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(fill="x", padx=22, pady=(0, 18))
        ctk.CTkButton(
            bot, text="完成", width=100, height=48,
            fg_color=COLORS["success"], hover_color="#15803d",
            font=ctk.CTkFont(size=18, weight="bold"),
            command=self.destroy).pack(side="right")

    def _select_all(self):
        for sub_var, _, _ in self.group["items"]:
            sub_var.set(True)

    def _select_none(self):
        for sub_var, _, _ in self.group["items"]:
            sub_var.set(False)


class ClinicSelectorWindow(ctk.CTkToplevel):
    def __init__(self, master, regions_map: dict, extra_clinics: list):
        super().__init__(master)
        self.title("選擇要產生的診所")
        self.geometry("520x680")
        self.minsize(450, 420)
        self.configure(fg_color=COLORS["bg"])

        self.master_app = master
        self.regions_map = regions_map
        self.extra_clinics = list(extra_clinics or [])

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
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkLabel(top, text="勾選要產生文件的診所",
                     font=ctk.CTkFont(size=19, weight="bold"),
                     text_color=COLORS["text"]).pack(side="left")

        ops = ctk.CTkFrame(self, fg_color="transparent")
        ops.pack(fill="x", padx=15, pady=(0, 6))
        ctk.CTkButton(ops, text="全選", width=70, height=28,
                      fg_color="transparent",
                      hover_color=COLORS["bg_card_hi"],
                      text_color=COLORS["text"],
                      border_color=COLORS["border"], border_width=1,
                      command=self._select_all).pack(side="left", padx=(0, 5))
        ctk.CTkButton(ops, text="全不選", width=70, height=28,
                      fg_color="transparent",
                      hover_color=COLORS["bg_card_hi"],
                      text_color=COLORS["text"],
                      border_color=COLORS["border"], border_width=1,
                      command=self._select_none).pack(side="left", padx=(0, 5))
        ctk.CTkButton(ops, text="反選", width=70, height=28,
                      fg_color="transparent",
                      hover_color=COLORS["bg_card_hi"],
                      text_color=COLORS["text"],
                      border_color=COLORS["border"], border_width=1,
                      command=self._invert).pack(side="left", padx=(0, 5))

        self.scroll = ctk.CTkScrollableFrame(self, fg_color=COLORS["bg_card"])
        self.scroll.pack(fill="both", expand=True, padx=15, pady=(2, 6))

        for region_label, clinics in self.ordered:
            self._build_group(region_label, clinics)

        self.count_lbl = ctk.CTkLabel(self, text="",
                                       text_color=COLORS["text_dim"],
                                       font=ctk.CTkFont(size=17),
                                       anchor="w")
        self.count_lbl.pack(fill="x", padx=15, pady=(0, 4))

        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(fill="x", padx=15, pady=(0, 15))
        ctk.CTkButton(bot, text="確認", width=90, height=48,
                      fg_color=COLORS["success"], hover_color="#15803d",
                      font=ctk.CTkFont(size=18, weight="bold"),
                      command=self._on_confirm).pack(side="right")
        ctk.CTkButton(bot, text="取消", width=80, height=48,
                      fg_color="transparent",
                      hover_color=COLORS["bg_card_hi"],
                      text_color=COLORS["text"],
                      border_color=COLORS["border"], border_width=1,
                      command=self.destroy).pack(side="right", padx=(0, 6))

        self._update_count()

    def _build_group(self, region_label: str, clinics: list):
        header = ctk.CTkFrame(self.scroll, fg_color=COLORS["bg_card_hi"],
                              corner_radius=4)
        header.pack(fill="x", pady=(8, 2))
        ctk.CTkLabel(header,
                     text=f"  📍 {region_label} ({len(clinics)} 間)",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=COLORS["text"]
                     ).pack(side="left", pady=4)
        ctk.CTkButton(header, text="全不選", width=70, height=24,
                      fg_color="transparent",
                      hover_color=COLORS["bg"],
                      text_color=COLORS["text_dim"],
                      border_color=COLORS["border"], border_width=1,
                      font=ctk.CTkFont(size=16),
                      command=lambda cs=clinics:
                          self._toggle_group(cs, False)
                      ).pack(side="right", padx=(2, 8), pady=2)
        ctk.CTkButton(header, text="全選", width=60, height=24,
                      fg_color="transparent",
                      hover_color=COLORS["bg"],
                      text_color=COLORS["text_dim"],
                      border_color=COLORS["border"], border_width=1,
                      font=ctk.CTkFont(size=16),
                      command=lambda cs=clinics:
                          self._toggle_group(cs, True)
                      ).pack(side="right", padx=2, pady=2)

        for c in clinics:
            ctk.CTkCheckBox(self.scroll, text=c,
                            variable=self.checks[c],
                            text_color=COLORS["text"],
                            fg_color=COLORS["accent"],
                            hover_color=COLORS["accent_hi"],
                            border_color=COLORS["border"], border_width=2,
                            checkmark_color="#ffffff",
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
            self.master_app._selected_clinics = None
        else:
            self.master_app._selected_clinics = selected
        self.master_app._update_clinic_filter_label()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
