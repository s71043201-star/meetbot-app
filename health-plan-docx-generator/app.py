"""健康台灣深耕計畫 — Word 核銷文件產生器（桌面 GUI 版）"""

import os
import sys
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox
from datetime import date

from reader import read_prescription_report
from excel_writer import (
    read_raw_records,
    generate_prescription_fee_excel,
    generate_execution_fee_excel,
    generate_health_mgmt_excel,
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
    generate_executor_receipts,
)

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
        self._section_label(main, "1. 匯入處方紀錄")
        frame_src = ctk.CTkFrame(main, fg_color="transparent")
        frame_src.pack(fill="x", pady=(0, 10))

        self.var_excel = ctk.StringVar()
        ctk.CTkEntry(frame_src, textvariable=self.var_excel,
                     placeholder_text="選擇處方紀錄 Excel 檔案...",
                     height=36).pack(side="left", fill="x", expand=True,
                                     padx=(0, 8))
        ctk.CTkButton(frame_src, text="選擇檔案", width=100, height=36,
                      command=self._browse_excel).pack(side="right")

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

        ctk.CTkLabel(row1, text="健管費最低份數").pack(side="left")
        self.var_min = ctk.StringVar(value="0")
        ctk.CTkEntry(row1, textvariable=self.var_min, width=70,
                     height=32).pack(side="left", padx=5)

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

        checks = [
            ("處方費核銷總表", self.var_gen_presc),
            ("處方執行費核銷總表", self.var_gen_exec),
            ("健康管理費總表", self.var_gen_health),
            ("處方處置費核銷總表", self.var_gen_treatment),
            ("執行人員民眾明細表", self.var_gen_patient),
            ("執行人員領據", self.var_gen_receipt),
        ]

        for i, (label, var) in enumerate(checks):
            r, c = divmod(i, 3)
            ctk.CTkCheckBox(opts_inner, text=label, variable=var,
                            font=ctk.CTkFont(size=13)).grid(
                                row=r, column=c, padx=10, pady=4, sticky="w")

        # ── 輸出目錄 ──
        self._section_label(main, "4. 輸出位置")
        frame_out = ctk.CTkFrame(main, fg_color="transparent")
        frame_out.pack(fill="x", pady=(0, 10))

        self.var_output = ctk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "Desktop", "核銷文件"))
        ctk.CTkEntry(frame_out, textvariable=self.var_output,
                     height=36).pack(side="left", fill="x", expand=True,
                                     padx=(0, 8))
        ctk.CTkButton(frame_out, text="選擇資料夾", width=100, height=36,
                      command=self._browse_output).pack(side="right")

        # ── 產生按鈕 ──
        self.btn_generate = ctk.CTkButton(
            main, text="產 生 文 件", height=48,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self._on_generate)
        self.btn_generate.pack(pady=15, fill="x")

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
            title="選擇處方紀錄 Excel",
            filetypes=[("Excel 檔案", "*.xlsx"), ("所有檔案", "*.*")])
        if path:
            self.var_excel.set(path)

    def _browse_output(self):
        path = filedialog.askdirectory(title="選擇輸出目錄")
        if path:
            self.var_output.set(path)

    def _log(self, text):
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def _on_generate(self):
        excel = self.var_excel.get().strip()
        if not excel or not os.path.exists(excel):
            messagebox.showerror("錯誤", "請選擇有效的 Excel 檔案")
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

    def _do_generate(self):
        excel = self.var_excel.get().strip()
        year = int(self.var_year.get())
        month = int(self.var_month.get())
        min_presc = int(self.var_min.get() or 0)
        output = self.var_output.get().strip()

        os.makedirs(output, exist_ok=True)

        self.after(0, lambda: self._log("讀取 Excel 中..."))
        self.after(0, lambda: self.progress.set(0.1))

        data = read_prescription_report(
            excel, report_year=year, report_month=month,
            min_prescriptions=min_presc,
        )

        self.after(0, lambda: self._log(
            f"  醫師: {len(data.doctors)} 位 | "
            f"診所: {len(data.health_mgmts)} 間 | "
            f"執行人員: {len(data.executors)} 位\n"
        ))

        prefix = f"{year}年{month:02d}月"

        # 月份主資料夾
        month_dir = os.path.join(output, prefix)
        os.makedirs(month_dir, exist_ok=True)

        # 產生 Excel 統計檔
        raw_records = read_raw_records(excel)
        presc_dir = os.path.join(month_dir, "處方費")
        os.makedirs(presc_dir, exist_ok=True)
        generate_prescription_fee_excel(raw_records, prefix, presc_dir)
        generate_execution_fee_excel(raw_records, prefix, presc_dir)
        hm_dir = os.path.join(month_dir, "健康管理費")
        os.makedirs(hm_dir, exist_ok=True)
        generate_health_mgmt_excel(raw_records, prefix, hm_dir)
        self.after(0, lambda: self._log("[OK] Excel 統計檔 (3 份)"))

        steps_done = 0
        total_steps = sum([
            self.var_gen_presc.get(),
            self.var_gen_exec.get(),
            self.var_gen_health.get(),
            self.var_gen_treatment.get(),
            self.var_gen_patient.get(),
            self.var_gen_receipt.get(),
        ])
        if total_steps == 0:
            total_steps = 1

        def step():
            nonlocal steps_done
            steps_done += 1
            self.after(0, lambda: self.progress.set(
                0.1 + 0.9 * steps_done / total_steps))

        def subdir(name):
            d = os.path.join(month_dir, name)
            os.makedirs(d, exist_ok=True)
            return d

        # 子資料夾 1: 處方費
        if self.var_gen_presc.get() and data.doctors:
            d = subdir("處方費")
            path = os.path.join(d, f"健康台灣深耕計畫_處方費-總表-{prefix}.docx")
            tmpl = DEFAULT_TEMPLATES["prescription"]
            if os.path.exists(tmpl):
                generate_prescription_fee_from_template(tmpl, data, path)
            else:
                generate_prescription_fee_doc(data, path)
            self.after(0, lambda: self._log("[OK] 處方費核銷總表"))
            step()

        if self.var_gen_exec.get() and data.doctors:
            d = subdir("處方費")
            path = os.path.join(d, f"健康台灣深耕計畫_處方執行費核銷總表-{prefix}.docx")
            tmpl = DEFAULT_TEMPLATES["execution"]
            if os.path.exists(tmpl):
                generate_execution_fee_from_template(tmpl, data, path)
            else:
                generate_execution_fee_doc(data, path)
            self.after(0, lambda: self._log("[OK] 處方執行費核銷總表"))
            step()

        # 子資料夾 2: 健康管理費
        if self.var_gen_health.get() and data.health_mgmts:
            d = subdir("健康管理費")
            path = os.path.join(d, f"健康台灣深耕計畫_健康管理費總表-{prefix}.docx")
            generate_health_mgmt_doc(data, path)
            self.after(0, lambda: self._log("[OK] 健康管理費總表"))
            step()

        # 子資料夾 3: 處方處置費
        if self.var_gen_treatment.get() and data.executors:
            d = subdir("處方處置費")
            path = os.path.join(d, f"健康台灣深耕計畫_處方處置費核銷總表-{prefix}.docx")
            generate_treatment_fee_doc(data, path)
            self.after(0, lambda: self._log("[OK] 處方處置費核銷總表"))
            step()

        if self.var_gen_patient.get() and data.executors:
            d = subdir("處方處置費")
            path = os.path.join(d, f"健康台灣深耕計畫_執行人員民眾明細表-{prefix}.docx")
            generate_executor_patient_list_doc(data, path)
            self.after(0, lambda: self._log("[OK] 執行人員民眾明細表"))
            step()

        # 子資料夾 4: 領據
        if self.var_gen_receipt.get() and data.executors:
            d = subdir("領據")
            generate_executor_receipts(data, d)
            count = sum(1 for ex in data.executors
                        if ex.receipt and ex.receipt.amount > 0)
            self.after(0, lambda: self._log(f"[OK] 領據 ({count} 份)"))
            step()

        self.after(0, lambda: self.progress.set(1.0))
        self.after(0, lambda: self._log(
            f"\n完成！共產生至: {output}"))
        self.after(0, lambda: messagebox.showinfo(
            "完成", f"所有文件已產生！\n\n輸出至: {output}"))
        self.after(0, lambda: os.startfile(output))


if __name__ == "__main__":
    app = App()
    app.mainloop()
