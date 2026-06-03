"""核銷文件產生器 — pywebview 入口（v39 白底 webview 版）

把 v38 customtkinter 的 GUI 換成 HTML/JS 前端，但邏輯（reader/excel_writer/
templates/email_sender 等）完全沿用 v37/v38 的 .py 檔。

API 物件 = JsApi class，前端透過 window.pywebview.api.<method> 呼叫。
"""

import os
import sys
import threading
import webview
from datetime import date

from config import PEOPLE_DIVISOR, MIN_PRESCRIPTIONS_DEFAULT
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
from bank_transfer_writer import (
    collect_scope_payees, generate_bank_transfer_file,
)
from bank_receipts_reader import read_payees_from_output
from people_db import load_people_db, create_template, export_to_db
from email_sender import build_email_jobs
import regions as regions_mod
import gdrive_sync
from config import (
    REGIONS_DRIVE_URL, PEOPLE_DB_DRIVE_URL, PEOPLE_DB_PASSWORD,
)


if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    BASE_DIR = sys._MEIPASS
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = APP_DIR

WEB_DIR = os.path.join(BASE_DIR, "web_ui")
TEMPLATE_DIR = os.path.join(BASE_DIR, "word_templates")

DEFAULT_TEMPLATES = {
    "prescription": os.path.join(TEMPLATE_DIR, "處方費_template.docx"),
    "execution": os.path.join(TEMPLATE_DIR, "處方執行費_template.docx"),
    "health_mgmt": os.path.join(TEMPLATE_DIR, "健康管理費_template.docx"),
}

# 富邦整批轉帳/匯款上傳檔範本（內建，隨匯出自動填空產出）
BANK_TEMPLATE = os.path.join(TEMPLATE_DIR, "富邦匯款範本.xlsm")


class JsApi:
    def __init__(self):
        self.window = None
        self._last = {"month_dir": None, "receipt_lookup": {},
                      "year": None, "month": None}

    # ─── helpers ───
    def _emit(self, event, payload):
        """將事件丟回 JS（透過 dispatchEvent）。"""
        if not self.window:
            return
        import json
        js = (f"window.dispatchEvent(new CustomEvent("
              f"{json.dumps(event)}, {{detail: {json.dumps(payload)}}}))")
        try:
            self.window.evaluate_js(js)
        except Exception:
            pass

    def _log(self, line):
        self._emit("log-line", line)

    def _progress(self, pct, status="", file="", kind=""):
        self._emit("progress-update",
                   {"pct": pct, "status": status, "file": file, "kind": kind})

    # ─── basic ───
    def getInitialState(self):
        today = date.today()
        return {
            "year": today.year - 1911,
            "month": today.month,
            "peopleDb": os.path.join(APP_DIR, "人員個資.xlsx"),
            "regionsDb": os.path.join(APP_DIR, "診所分區.xlsx"),
            "output": os.path.join(APP_DIR, "核銷文件"),
        }

    def pickFile(self, accept=""):
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("Excel (*.xlsx)", "所有檔案 (*.*)") if "xlsx" in accept
                       else ("所有檔案 (*.*)",))
        if result and len(result) > 0:
            return result[0]
        return None

    def pickFolder(self):
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return result[0]
        return None

    def fileExists(self, path):
        return bool(path) and os.path.exists(path)

    def openFile(self, path):
        try:
            os.startfile(path)
            return True
        except Exception as e:
            return False

    # ─── 富邦匯款獨立工具（匯入已產出核銷資料 → 只產生匯款檔）───
    def getBankToolInit(self):
        today = date.today()
        return {
            "year": today.year - 1911,
            "month": today.month,
            "output": os.path.join(APP_DIR, "核銷文件"),
        }

    def openBankTool(self):
        url = os.path.join(WEB_DIR, "bank_tool.html")
        try:
            webview.create_window("富邦匯款上傳檔", url, js_api=self,
                                  width=760, height=680)
        except Exception as e:
            self._log(f"⚠ 開啟富邦匯款視窗失敗：{e}")
            return False
        return True

    def generateBankFromReceipts(self, folder, year, month, people_db=""):
        folder = (folder or "").strip()
        if not folder or not os.path.isdir(folder):
            raise RuntimeError("請選擇已產出的核銷月份資料夾")
        year = int(year)
        month = int(month)
        people_lookup = {}
        if people_db and os.path.exists(people_db):
            self._log(f"讀取個資檔（補身分別）：{people_db}")
            people_lookup = load_people_db(people_db)
        self._log(f"讀取已產出領據：{folder}")
        payees = read_payees_from_output(
            folder, people_lookup=people_lookup, progress_cb=self._log)
        if not payees:
            raise RuntimeError("此資料夾內找不到任何領據（*領據*.docx）")
        out_path, stats = generate_bank_transfer_file(
            payees, year, month, folder,
            template_path=BANK_TEMPLATE, progress_cb=self._log)
        if out_path:
            try:
                os.startfile(folder)
            except Exception:
                pass
        return {"path": out_path or "", "stats": stats}

    # ─── Google Drive 同步 ───
    def _regions_cache_path(self):
        return os.path.join(APP_DIR, "診所分區.xlsx")

    def _people_cache_path(self):
        return os.path.join(APP_DIR, "人員個資.xlsx")

    def syncRegionsFromDrive(self):
        """背景下載診所分區 → APP_DIR/診所分區.xlsx；失敗時保留原本機檔。
        無密碼，回傳 {ok, path, message}。
        """
        dest = self._regions_cache_path()
        if not REGIONS_DRIVE_URL:
            return {"ok": False, "path": dest if os.path.exists(dest) else "",
                    "message": "未設定雲端連結"}
        try:
            gdrive_sync.download_xlsx(REGIONS_DRIVE_URL, dest)
            self._log(f"✓ 診所分區已從雲端更新：{dest}")
            return {"ok": True, "path": dest, "message": "雲端同步完成"}
        except Exception as e:
            self._log(f"⚠ 診所分區雲端同步失敗，使用本機快取：{e}")
            return {"ok": False,
                    "path": dest if os.path.exists(dest) else "",
                    "message": f"雲端同步失敗：{e}"}

    def syncPeopleFromDrive(self, password):
        """密碼正確才下載人員個資 → APP_DIR/人員個資.xlsx。
        回傳 {ok, path, message}。
        """
        if not password or password != PEOPLE_DB_PASSWORD:
            return {"ok": False, "path": "", "message": "密碼錯誤"}

        dest = self._people_cache_path()
        if not PEOPLE_DB_DRIVE_URL:
            return {"ok": False, "path": "", "message": "未設定雲端連結"}
        try:
            gdrive_sync.download_xlsx(PEOPLE_DB_DRIVE_URL, dest)
            self._log(f"✓ 人員個資已從雲端帶入：{dest}")
            return {"ok": True, "path": dest, "message": "雲端帶入完成"}
        except Exception as e:
            self._log(f"⚠ 人員個資雲端帶入失敗：{e}")
            return {"ok": False, "path": "",
                    "message": f"雲端帶入失敗：{e}"}

    # ─── people db ───
    def createPeopleTemplate(self, path):
        if not path:
            path = os.path.join(APP_DIR, "人員個資.xlsx")
        if os.path.exists(path):
            # 前端要先 confirm；這邊直接覆蓋（前端有判斷）
            pass
        create_template(path)
        return path

    def importFromReceipts(self, receipts_dir, db_path):
        if not db_path:
            db_path = os.path.join(APP_DIR, "人員個資.xlsx")
        self._log("\n── 從舊領據匯入 ──")
        lookup = load_receipts_from_dir(
            receipts_dir,
            progress_cb=lambda m: self._log(m))
        if not lookup:
            raise RuntimeError("資料夾內沒有找到領據檔案")
        count = export_to_db(lookup, db_path)
        return {"count": count, "path": db_path}

    # ─── regions ───
    def createRegionsTemplate(self, path):
        if not path:
            path = os.path.join(APP_DIR, "診所分區.xlsx")
        regions_mod.create_template(path)
        return path

    def loadClinics(self, regions_path, excel_path):
        regions_map = regions_mod.load_regions(regions_path)
        if not regions_map or not any(regions_map.values()):
            raise RuntimeError("診所分區檔不存在或為空白，請先設定")
        groups = []
        for r in regions_mod.REGION_NAMES:
            cs = regions_map.get(r, [])
            if cs:
                groups.append((r, list(cs)))
        # 額外：Excel 有但分區檔沒列的
        extras = []
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
                        extras.append(c)
            except Exception:
                pass
        if extras:
            groups.append(("其他 (處方 Excel 有但分區檔未列)", extras))
        return {"groups": groups}

    # ─── generate ───
    def generateDocs(self, s):
        # 在背景 thread 跑（不要塞住 webview）
        done_event = threading.Event()
        result = {"err": None}

        def worker():
            try:
                self._do_generate(s)
            except Exception as e:
                import traceback
                traceback.print_exc()
                result["err"] = str(e)
            finally:
                done_event.set()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        done_event.wait()
        if result["err"]:
            raise RuntimeError(result["err"])
        return True

    def _do_generate(self, s):
        issuance = s["excel"].strip()
        execution = (s.get("execExcel") or "").strip() or issuance
        year = int(s["year"])
        month = int(s["month"])
        region_choice = s["region"]
        output = s["output"].strip()
        os.makedirs(output, exist_ok=True)

        self._log("讀取 Excel 中...")
        self._progress(0.05, "讀取 Excel…", os.path.basename(issuance))

        data = read_prescription_report(
            issuance, execution_path=execution,
            report_year=year, report_month=month,
            min_prescriptions=0)
        raw_iss = read_raw_records(issuance)
        raw_exe = read_raw_records(execution) if execution != issuance else raw_iss

        self._log(f"  醫師: {len(data.doctors)} 位 | 診所: {len(data.health_mgmts)} 間")

        receipt_lookup = {}
        if s.get("peopleDb") and os.path.exists(s["peopleDb"]):
            self._log("讀取個資檔…")
            receipt_lookup = load_people_db(s["peopleDb"])

        clinic_to_person = {
            info.clinic_name: (info.recipient_name or "")
            for info in receipt_lookup.values()
            if info.role == "診所行政人員" and info.clinic_name
        }
        for hm in data.health_mgmts:
            inst = hm.medical_institution
            if inst in clinic_to_person:
                hm.clinic_person = clinic_to_person[inst]
            else:
                for k, p in clinic_to_person.items():
                    if k and (k in inst or inst in k):
                        hm.clinic_person = p
                        break

        regions_map = regions_mod.load_regions(s.get("regionsDb", ""))
        all_clinics = set()
        for d in data.doctors:
            all_clinics.add(d.medical_institution)
        for hm in data.health_mgmts:
            all_clinics.add(hm.medical_institution)

        region_to_clinics = {r: set() for r in regions_mod.REGION_NAMES}
        region_to_clinics["其他"] = set()
        for c in all_clinics:
            r = regions_mod.find_region(c, regions_map) or "其他"
            region_to_clinics.setdefault(r, set()).add(c)

        sel = s.get("selectedClinics")
        if sel is not None:
            kept = set()
            if sel:
                for c in all_clinics:
                    if c in sel or any(x in c or c in x for x in sel):
                        kept.add(c)
            for r in list(region_to_clinics.keys()):
                region_to_clinics[r] &= kept
            self._log(f"進階篩選：鎖定 {len(kept)} 間診所")

        prefix = f"{year}年{month:02d}月"
        month_root = os.path.join(output, prefix)
        os.makedirs(month_root, exist_ok=True)

        thresholds = {r: int(s["minByRegion"].get(r, "0") or "0")
                      for r in regions_mod.REGION_NAMES}

        scopes = []
        if region_choice == "全部":
            for r in regions_mod.REGION_NAMES:
                cs = region_to_clinics.get(r, set())
                if cs:
                    scopes.append((r, cs, thresholds.get(r, 0),
                                   os.path.join(month_root, r), False))
            if region_to_clinics.get("其他"):
                scopes.append(("其他", region_to_clinics["其他"], 0,
                               os.path.join(month_root, "其他"), False))
            if data.executors:
                scopes.append(("課程老師", set(), 0,
                               os.path.join(month_root, "課程老師"), True))
        else:
            scopes.append((region_choice,
                           region_to_clinics.get(region_choice, set()),
                           thresholds.get(region_choice, 0),
                           os.path.join(month_root, region_choice), True))

        self._progress(0.15, "產生 Word 文件中…")

        gen_bank = s.get("gen_bank_transfer", True)
        bank_payees = []

        all_pending = []
        merge_bundles = []
        for label, allowed, thr, mdir, prod_exec in scopes:
            ds = self._filter_data(data, allowed)
            ri = [r for r in raw_iss if len(r) > 7 and str(r[7] or "") in allowed]
            re_ = [r for r in raw_exe if len(r) > 7 and str(r[7] or "") in allowed]
            for hm in ds.health_mgmts:
                hm.is_qualified = (thr == 0 or hm.prescription_count >= thr)
            ds.min_prescriptions = thr
            if not (ds.doctors or ds.health_mgmts or (prod_exec and ds.executors)):
                self._log(f"[{label}] 無資料，略過")
                continue
            pending, hi, ei, di = self._produce_for_scope(
                label, ds, ri, re_, mdir, prefix, thr,
                receipt_lookup, prod_exec, s)
            all_pending.extend(pending)
            merge_bundles.append((hi, ei, di))
            if gen_bank:
                collect_scope_payees(bank_payees, ds, receipt_lookup, prod_exec)

        if all_pending:
            self._log(f"\n批次轉換 {len(all_pending)} 份 Word → PDF…")
            self._progress(0.7, "PDF 轉檔中…")

            def pdf_cb(done, total, name):
                pct = 0.7 + 0.28 * done / total
                self._progress(pct, f"PDF {done}/{total}",
                               os.path.basename(name) if name else "")
                if done % 10 == 0:
                    self._log(f"  [{done}/{total}] {name}")
            _convert_docx_list_to_pdf(all_pending, progress_cb=pdf_cb)

        master_password = (s.get("masterPassword") or "").strip() or None

        for hi, ei, di in merge_bundles:
            if hi: merge_health_mgmt_pdfs(*hi, master_password=master_password)
            if ei: merge_executor_pdfs(*ei, master_password=master_password)
            if di: merge_doctor_receipt_pdfs(di, master_password=master_password)

        # === 富邦整批轉帳/匯款上傳檔（填入內建範本，與領據同月份）===
        if gen_bank and bank_payees:
            try:
                self._progress(0.99, "產生富邦匯款上傳檔…")
                generate_bank_transfer_file(
                    bank_payees, year, month, month_root,
                    template_path=BANK_TEMPLATE, progress_cb=self._log)
            except Exception as e:
                self._log(f"[WARN] 富邦匯款上傳檔產生失敗：{e}")

        self._progress(1.0, "✓ 全部完成", "", "success")
        self._log(f"\n完成！輸出至: {output}")
        self._last = {
            "month_dir": month_root, "receipt_lookup": receipt_lookup,
            "year": year, "month": month}
        try:
            os.startfile(output)
        except Exception:
            pass

    def _filter_data(self, data, allowed):
        from models import AllData
        return AllData(
            report_year=data.report_year, report_month=data.report_month,
            doctors=[d for d in data.doctors if d.medical_institution in allowed],
            health_mgmts=[h for h in data.health_mgmts if h.medical_institution in allowed],
            executors=data.executors,
            min_prescriptions=data.min_prescriptions)

    def _produce_for_scope(self, label, data, raw_iss, raw_exe,
                           month_dir, prefix, min_p, lookup, prod_exec, s):
        os.makedirs(month_dir, exist_ok=True)
        OTHER = "其他內容"

        def agg(name):
            d = os.path.join(month_dir, OTHER, name)
            os.makedirs(d, exist_ok=True)
            return d

        all_p = []
        h_info = e_info = d_info = None

        if s["gen_doctor_summary"] and data.doctors:
            d = agg("處方費、處方執行費總表明細表合併檔與Excel")
            try:
                generate_prescription_fee_excel(raw_iss, prefix, d)
                generate_execution_fee_excel(raw_exe, prefix, d)
            except Exception:
                pass
            p1 = os.path.join(d, f"健康台灣深耕計畫_處方費-總表-{prefix}.docx")
            t1 = DEFAULT_TEMPLATES["prescription"]
            if os.path.exists(t1):
                generate_prescription_fee_from_template(t1, data, p1)
            else:
                generate_prescription_fee_doc(data, p1)
            all_p.append(os.path.abspath(p1))
            p2 = os.path.join(d, f"健康台灣深耕計畫_處方執行費核銷總表-{prefix}.docx")
            t2 = DEFAULT_TEMPLATES["execution"]
            if os.path.exists(t2):
                generate_execution_fee_from_template(t2, data, p2)
            else:
                generate_execution_fee_doc(data, p2)
            all_p.append(os.path.abspath(p2))
            self._log(f"[{label}] 醫師彙整總表")

        if any([s["gen_doctor_presc_detail"], s["gen_doctor_exec_detail"],
                s["gen_doctor_receipt"]]) and data.doctors:
            dr = generate_doctor_receipts(
                data, month_dir, receipt_lookup=lookup, also_pdf=False,
                emit_presc_detail=s["gen_doctor_presc_detail"],
                emit_exec_detail=s["gen_doctor_exec_detail"],
                emit_receipt=s["gen_doctor_receipt"])
            if dr:
                d_info = dr
                seen = set()
                for _, _, dd, r, _, _ in dr:
                    for p in (dd, r):
                        if p and p not in seen:
                            all_p.append(p)
                            seen.add(p)
            self._log(f"[{label}] 醫師個人文件")

        if s["gen_health_summary"] and data.health_mgmts:
            d = agg("健康管理費合併總表與個人excel")
            try:
                generate_health_mgmt_excel(raw_iss, prefix, d)
            except Exception:
                pass
            p = os.path.join(d, f"健康台灣深耕計畫_健康管理費總表-{prefix}.docx")
            generate_health_mgmt_doc(data, p, min_prescriptions=min_p)
            all_p.append(os.path.abspath(p))
            try:
                pcd = os.path.join(d, "個別Excel")
                os.makedirs(pcd, exist_ok=True)
                cmap = {hm.medical_institution: (hm.clinic_person or hm.medical_institution)
                        for hm in data.health_mgmts}
                generate_health_mgmt_excel_per_clinic(raw_iss, prefix, pcd, clinic_to_person=cmap)
            except Exception:
                pass
            self._log(f"[{label}] 健管費彙整")

        if any([s["gen_health_detail"], s["gen_health_receipt"]]) and data.health_mgmts:
            r = generate_health_mgmt_individual_docs(
                data, month_dir, receipt_lookup=lookup, also_pdf=False,
                emit_detail=s["gen_health_detail"],
                emit_receipt=s["gen_health_receipt"])
            if r:
                hd, hrd = r
                h_info = (hd, hrd)
                for _, dd, rr, _ in hd:
                    for p in (dd, rr):
                        if p: all_p.append(p)
            self._log(f"[{label}] 診所個人文件")

        if prod_exec and s["gen_treatment_summary"] and data.executors:
            d = agg("處方處置費合併總表word")
            p1 = os.path.join(d, f"健康台灣深耕計畫_處方處置費核銷總表-{prefix}.docx")
            generate_treatment_fee_doc(data, p1)
            p2 = os.path.join(d, f"健康台灣深耕計畫_執行人員民眾明細表-{prefix}.docx")
            generate_executor_patient_list_doc(data, p2)
            self._log(f"[{label}] 處置費彙整")

        if prod_exec and any([s["gen_treatment_detail"], s["gen_treatment_receipt"]]) \
                and data.executors:
            r = generate_executor_merged_docs(
                data, month_dir, also_pdf=False,
                receipt_lookup=lookup,
                emit_detail=s["gen_treatment_detail"],
                emit_receipt=s["gen_treatment_receipt"])
            if r:
                ed, erd = r
                e_info = (ed, erd)
                for _, _, dd, rr, _ in ed:
                    for p in (dd, rr):
                        if p: all_p.append(p)
            self._log(f"[{label}] 老師個人文件")

        return all_p, h_info, e_info, d_info

    # ─── email preview ───
    def openEmailPreview(self, s):
        year = int(s["year"])
        month = int(s["month"])
        prefix = f"{year}年{month:02d}月"
        month_dir = self._last.get("month_dir")
        if not month_dir or self._last.get("year") != year \
                or self._last.get("month") != month or not os.path.isdir(month_dir):
            month_dir = os.path.join(s["output"].strip(), prefix)
        if not os.path.isdir(month_dir):
            raise RuntimeError(f"找不到月份資料夾：{month_dir}")
        receipt_lookup = self._last.get("receipt_lookup") or {}
        if not receipt_lookup and s.get("peopleDb") and os.path.exists(s["peopleDb"]):
            receipt_lookup = load_people_db(s["peopleDb"])
        jobs = build_email_jobs(month_dir, receipt_lookup, year, month)
        if not jobs:
            raise RuntimeError(f"在 {month_dir} 找不到合併 PDF")

        # 開啟新 webview 視窗
        from email_preview_webview import open_email_preview
        open_email_preview(jobs, s["senderEmail"])
        return True


def main():
    api = JsApi()
    html_path = os.path.join(WEB_DIR, "index.html")
    win = webview.create_window(
        "⚡ 核銷文件產生器 v39",
        url=html_path,
        js_api=api,
        width=1100, height=820,
        min_size=(960, 680))
    api.window = win

    def _bg_regions_sync():
        try:
            gdrive_sync.download_xlsx(
                REGIONS_DRIVE_URL, api._regions_cache_path())
            api._log(f"✓ 診所分區已從雲端更新")
        except Exception as e:
            api._log(f"⚠ 診所分區雲端同步失敗，使用本機快取：{e}")

    if REGIONS_DRIVE_URL:
        threading.Thread(target=_bg_regions_sync, daemon=True).start()

    webview.start(debug=False)


if __name__ == "__main__":
    main()
