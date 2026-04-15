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
    generate_executor_merged_docs,
    generate_doctor_receipts,
)
from receipt_reader import load_receipts_from_dir
from people_db import load_people_db, create_template, export_to_db


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

        # ── 輸出目錄 ──
        self._section_label(main, "5. 輸出位置")
        frame_out = ctk.CTkFrame(main, fg_color="transparent")
        frame_out.pack(fill="x", pady=(0, 10))

        self.var_output = ctk.StringVar(
            value=os.path.join(APP_DIR, "核銷文件"))
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
        """將 Word 檔轉成同目錄的 PDF（需要 Word 已安裝）"""
        try:
            import win32com.client
            pdf_path = docx_path.replace(".docx", ".pdf")
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            try:
                doc = word.Documents.Open(os.path.abspath(docx_path))
                doc.SaveAs(os.path.abspath(pdf_path), FileFormat=17)
                doc.Close()
            finally:
                word.Quit()
        except Exception:
            pass

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

        # 預先載入人員個資（整個 _do_generate 共用）
        receipt_lookup = {}
        db_path = self.var_people_db.get().strip()
        if db_path and os.path.exists(db_path):
            self.after(0, lambda: self._log("讀取人員個資檔..."))
            receipt_lookup = load_people_db(db_path)

        # 建立「診所名 → 人名」反查表（用於健管費診所人員修正）
        clinic_to_person = {
            info.clinic_name: person_name
            for person_name, info in receipt_lookup.items()
            if info.role == "診所行政人員" and info.clinic_name
        }

        def _match_clinic(institution):
            """依序嘗試精確→子字串→最長共同前綴比對，回傳人名或 None"""
            if institution in clinic_to_person:
                return clinic_to_person[institution]
            # 子字串比對（雙向）
            for key, person in clinic_to_person.items():
                if key in institution or institution in key:
                    return person
            # 最長共同前綴比對（≥3字即視為同一診所）
            # 例：「王志靈內科診所」vs「王志靈診所」→ 前綴「王志靈」=3字 → 匹配
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

        steps_done = 0
        total_steps = sum([
            self.var_gen_presc.get(),
            self.var_gen_exec.get(),
            self.var_gen_health.get(),
            self.var_gen_treatment.get(),
            self.var_gen_patient.get(),
            self.var_gen_receipt.get(),
            self.var_gen_doctor_receipt.get(),
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
            self._docx_to_pdf(path)
            self.after(0, lambda: self._log("[OK] 處方費核銷總表 + PDF"))
            step()

        if self.var_gen_exec.get() and data.doctors:
            d = subdir("處方費")
            path = os.path.join(d, f"健康台灣深耕計畫_處方執行費核銷總表-{prefix}.docx")
            tmpl = DEFAULT_TEMPLATES["execution"]
            if os.path.exists(tmpl):
                generate_execution_fee_from_template(tmpl, data, path)
            else:
                generate_execution_fee_doc(data, path)
            self._docx_to_pdf(path)
            self.after(0, lambda: self._log("[OK] 處方執行費核銷總表 + PDF"))
            step()

        # 子資料夾 2: 健康管理費
        if self.var_gen_health.get() and data.health_mgmts:
            d = subdir("健康管理費")
            path = os.path.join(d, f"健康台灣深耕計畫_健康管理費總表-{prefix}.docx")
            generate_health_mgmt_doc(data, path, min_prescriptions=min_presc)
            self._docx_to_pdf(path)
            self.after(0, lambda: self._log("[OK] 健康管理費總表 + PDF"))
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

        # 子資料夾 4: 執行人員領據（處方處置費，含總表+明細合併PDF）
        if self.var_gen_receipt.get() and data.executors:
            d = subdir("處方處置費領據")
            self.after(0, lambda: self._log("產生處方處置費領據（含PDF）..."))
            generate_executor_merged_docs(data, d, also_pdf=True,
                                          receipt_lookup=receipt_lookup)
            count = sum(1 for ex in data.executors
                        if ex.receipt and ex.receipt.amount > 0)
            self.after(0, lambda: self._log(f"[OK] 處方處置費領據 ({count} 份，含合併PDF)"))
            step()

        # 子資料夾 5: 醫師處方費/執行費領據（各自獨立子資料夾）
        if self.var_gen_doctor_receipt.get() and data.doctors:
            d_presc = subdir("處方費領據")
            d_exec  = subdir("處方執行費領據")
            generate_doctor_receipts(data, d_presc, d_exec,
                                     receipt_lookup=receipt_lookup)
            count = sum(1 for doc in data.doctors
                        if doc.prescription_fee > 0 or doc.execution_fee > 0)
            self.after(0, lambda: self._log(f"[OK] 醫師領據 ({count} 位，分處方費/處方執行費)"))
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
