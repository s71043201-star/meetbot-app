"""核銷文件產生器 — 純瀏覽器版（取代 pywebview）

跑法：
    python app_server.py

開一個本機 HTTP server (port 5173)，並用預設瀏覽器打開頁面。
所有原本 pywebview 的 JsApi 都包成 POST /api/<method>，事件透過 SSE /api/events 推。

選檔/選資料夾用 tkinter.filedialog（Python 內建，不需另裝）。
"""

import os
import sys
import json
import queue
import threading
import traceback
import webbrowser
import http.server
import socketserver
import urllib.parse
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
from people_db import load_people_db, create_template, export_to_db
from email_sender import build_email_jobs
import regions as regions_mod


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

PORT = 5173

# ───── 事件 broker：SSE ─────
_event_q = queue.Queue()


def emit(event, payload):
    _event_q.put({"event": event, "data": payload})


def _log(line):
    emit("log-line", line)


def _progress(pct, status="", file="", kind=""):
    emit("progress-update", {
        "pct": pct, "status": status, "file": file, "kind": kind})


# ───── 對話框：必須在主執行緒處理 Tk，用 queue 傳遞請求 ─────
_dlg_request_q = queue.Queue()
_dlg_result_q = queue.Queue()
_dlg_serial_lock = threading.Lock()


def _pick_file(xlsx_only=False):
    """從任意 thread 呼叫；阻塞直到主 thread 處理完。"""
    with _dlg_serial_lock:
        while not _dlg_result_q.empty():
            try:
                _dlg_result_q.get_nowait()
            except queue.Empty:
                break
        _dlg_request_q.put({"kind": "file", "xlsx_only": xlsx_only})
        return _dlg_result_q.get()


def _pick_folder():
    with _dlg_serial_lock:
        while not _dlg_result_q.empty():
            try:
                _dlg_result_q.get_nowait()
            except queue.Empty:
                break
        _dlg_request_q.put({"kind": "folder"})
        return _dlg_result_q.get()


def _dialog_pump(root):
    """主 thread 上跑：每 50ms 檢查 queue，有請求就開對話框。"""
    try:
        while True:
            try:
                req = _dlg_request_q.get_nowait()
            except queue.Empty:
                break
            try:
                from tkinter import filedialog
                if req["kind"] == "file":
                    types = [("Excel", "*.xlsx"), ("All", "*.*")] \
                        if req.get("xlsx_only") else [("All", "*.*")]
                    p = filedialog.askopenfilename(parent=root, filetypes=types)
                    _dlg_result_q.put(p or "")
                elif req["kind"] == "folder":
                    p = filedialog.askdirectory(parent=root)
                    _dlg_result_q.put(p or "")
                else:
                    _dlg_result_q.put("")
            except Exception:
                traceback.print_exc()
                _dlg_result_q.put("")
    finally:
        root.after(50, lambda: _dialog_pump(root))


# ───── JsApi 邏輯（從 app_webview.py 搬過來）─────
class JsApi:
    def __init__(self):
        self._last = {"month_dir": None, "receipt_lookup": {},
                      "year": None, "month": None}

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
        return _pick_file(xlsx_only="xlsx" in (accept or "")) or None

    def pickFolder(self):
        return _pick_folder() or None

    def fileExists(self, path):
        return bool(path) and os.path.exists(path)

    def openFile(self, path):
        try:
            os.startfile(path)
            return True
        except Exception:
            return False

    def createPeopleTemplate(self, path):
        if not path:
            path = os.path.join(APP_DIR, "人員個資.xlsx")
        create_template(path)
        return path

    def importFromReceipts(self, receipts_dir, db_path):
        if not db_path:
            db_path = os.path.join(APP_DIR, "人員個資.xlsx")
        _log("\n── 從舊領據匯入 ──")
        lookup = load_receipts_from_dir(
            receipts_dir,
            progress_cb=lambda m: _log(m))
        if not lookup:
            raise RuntimeError("資料夾內沒有找到領據檔案")
        count = export_to_db(lookup, db_path)
        return {"count": count, "path": db_path}

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

    # 產文件主流程：在背景 thread 跑（route handler 已經在 thread 內，所以直接呼叫）
    def generateDocs(self, s):
        try:
            self._do_generate(s)
            return True
        except Exception as e:
            traceback.print_exc()
            raise

    def _do_generate(self, s):
        issuance = s["excel"].strip()
        execution = (s.get("execExcel") or "").strip() or issuance
        year = int(s["year"])
        month = int(s["month"])
        region_choice = s["region"]
        output = s["output"].strip()
        os.makedirs(output, exist_ok=True)

        _log("讀取 Excel 中...")
        _progress(0.05, "讀取 Excel…", os.path.basename(issuance))

        data = read_prescription_report(
            issuance, execution_path=execution,
            report_year=year, report_month=month,
            min_prescriptions=0)
        raw_iss = read_raw_records(issuance)
        raw_exe = read_raw_records(execution) if execution != issuance else raw_iss

        _log(f"  醫師: {len(data.doctors)} 位 | 診所: {len(data.health_mgmts)} 間")

        receipt_lookup = {}
        if s.get("peopleDb") and os.path.exists(s["peopleDb"]):
            _log("讀取個資檔…")
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
            _log(f"進階篩選：鎖定 {len(kept)} 間診所")

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

        _progress(0.15, "產生 Word 文件中…")

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
                _log(f"[{label}] 無資料，略過")
                continue
            pending, hi, ei, di = self._produce_for_scope(
                label, ds, ri, re_, mdir, prefix, thr,
                receipt_lookup, prod_exec, s)
            all_pending.extend(pending)
            merge_bundles.append((hi, ei, di))

        if all_pending:
            _log(f"\n批次轉換 {len(all_pending)} 份 Word → PDF…")
            _progress(0.7, "PDF 轉檔中…")

            def pdf_cb(done, total, name):
                pct = 0.7 + 0.28 * done / total
                _progress(pct, f"PDF {done}/{total}",
                          os.path.basename(name) if name else "")
                if done % 10 == 0:
                    _log(f"  [{done}/{total}] {name}")
            _convert_docx_list_to_pdf(all_pending, progress_cb=pdf_cb)

        for hi, ei, di in merge_bundles:
            if hi: merge_health_mgmt_pdfs(*hi)
            if ei: merge_executor_pdfs(*ei)
            if di: merge_doctor_receipt_pdfs(di)

        _progress(1.0, "✓ 全部完成", "", "success")
        _log(f"\n完成！輸出至: {output}")
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
            _log(f"[{label}] 醫師彙整總表")

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
                for _, _, dd, r, _ in dr:
                    for p in (dd, r):
                        if p and p not in seen:
                            all_p.append(p)
                            seen.add(p)
            _log(f"[{label}] 醫師個人文件")

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
            _log(f"[{label}] 健管費彙整")

        if any([s["gen_health_detail"], s["gen_health_receipt"]]) and data.health_mgmts:
            r = generate_health_mgmt_individual_docs(
                data, month_dir, receipt_lookup=lookup, also_pdf=False,
                emit_detail=s["gen_health_detail"],
                emit_receipt=s["gen_health_receipt"])
            if r:
                hd, hrd = r
                h_info = (hd, hrd)
                for _, dd, rr in hd:
                    for p in (dd, rr):
                        if p: all_p.append(p)
            _log(f"[{label}] 診所個人文件")

        if prod_exec and s["gen_treatment_summary"] and data.executors:
            d = agg("處方處置費合併總表word")
            p1 = os.path.join(d, f"健康台灣深耕計畫_處方處置費核銷總表-{prefix}.docx")
            generate_treatment_fee_doc(data, p1)
            p2 = os.path.join(d, f"健康台灣深耕計畫_執行人員民眾明細表-{prefix}.docx")
            generate_executor_patient_list_doc(data, p2)
            _log(f"[{label}] 處置費彙整")

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
                for _, _, dd, rr in ed:
                    for p in (dd, rr):
                        if p: all_p.append(p)
            _log(f"[{label}] 老師個人文件")

        return all_p, h_info, e_info, d_info

    # email 預覽：把 jobs 與 sender 存到 module-level，讓另一個頁面去拿
    def openEmailPreview(self, s):
        global _email_state
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
        _email_state["jobs"] = jobs
        _email_state["sender"] = s["senderEmail"]
        # 開新分頁
        webbrowser.open(f"http://127.0.0.1:{PORT}/email_preview.html")
        return True


# ─── email 寄送（搬自 email_preview_webview.py）───
import time
from email_sender import EmailJob, SmtpAuthError, send_via_gmail_smtp

SEND_INTERVAL_SECONDS = 1.5
_INVISIBLE_ORDS = {0x200B, 0x200C, 0x200D, 0xFEFF, 0x3000, 0x00A0}
_email_state = {"jobs": [], "sender": ""}


def _normalize_app_password(raw):
    cleaned = []
    for c in raw:
        if c.isspace() or ord(c) in _INVISIBLE_ORDS:
            continue
        if 32 < ord(c) < 127:
            cleaned.append(c)
    return "".join(cleaned)


def _job_to_dict(j):
    return {
        "person_name": j.person_name,
        "role": j.role,
        "clinic_name": j.clinic_name or "",
        "to_email": j.to_email or "",
        "zone": j.zone or "",
        "status": j.status,
        "error": j.error or "",
        "attachments_count": len(j.attachments),
        "selected": j.selected,
    }


class EmailApi:
    def getEmailData(self):
        return {
            "sender": _email_state["sender"],
            "jobs": [_job_to_dict(j) for j in _email_state["jobs"]],
        }

    def sendBatch(self, app_pw_raw, indices):
        pw = _normalize_app_password(app_pw_raw)
        sent = failed = 0
        for idx in indices:
            j = _email_state["jobs"][idx]
            if j.status == "sent":
                continue
            if not j.to_email or not j.attachments:
                j.status = "skipped"
                continue
            try:
                send_via_gmail_smtp(_email_state["sender"], pw, j)
                j.status = "sent"
                sent += 1
            except SmtpAuthError as e:
                j.status = "failed"
                j.error = "認證失敗：" + str(e)
                failed += 1
                break
            except Exception as e:
                j.status = "failed"
                j.error = str(e)
                failed += 1
            time.sleep(SEND_INTERVAL_SECONDS)
        return {
            "sent": sent, "failed": failed,
            "jobs": [_job_to_dict(x) for x in _email_state["jobs"]],
        }


# ─── HTTP server ───
api = JsApi()
email_api = EmailApi()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, *a, **k):
        pass  # 安靜模式

    # ── SSE：/api/events ──
    def _serve_events(self):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = _event_q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                payload = (
                    f"event: {msg['event']}\n"
                    f"data: {json.dumps(msg['data'], ensure_ascii=False)}\n\n"
                ).encode("utf-8")
                self.wfile.write(payload)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError,
                ConnectionAbortedError, OSError):
            return
        except Exception:
            traceback.print_exc()
            return

    def _json_response(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/api/events":
            return self._serve_events()
        if url.path == "/" or url.path == "":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if not url.path.startswith("/api/"):
            self.send_error(404, "Not Found")
            return
        name = url.path[len("/api/"):]
        ln = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(ln) if ln else b""
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            body = {}
        args = body.get("args", [])

        # 路由：先 main api，再 email api
        target = api if hasattr(api, name) else (
            email_api if hasattr(email_api, name) else None)
        if target is None:
            return self._json_response(404, {"err": f"unknown api: {name}"})
        try:
            fn = getattr(target, name)
            result = fn(*args)
            return self._json_response(200, {"ok": True, "result": result})
        except Exception as e:
            traceback.print_exc()
            return self._json_response(
                200, {"ok": False, "err": str(e)})


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    httpd = ThreadedHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"\n核銷文件產生器 v39 — 已啟動於 http://127.0.0.1:{PORT}\n")
    print("（請保留此視窗。關掉視窗 = 關掉程式）\n")

    def serve():
        try:
            httpd.serve_forever()
        except Exception:
            traceback.print_exc()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    webbrowser.open(f"http://127.0.0.1:{PORT}/")

    # 主 thread 跑 Tk mainloop（處理選檔對話框）
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.after(50, lambda: _dialog_pump(root))
        root.mainloop()
    except Exception:
        traceback.print_exc()
        # 沒 tk 也讓 server 繼續跑
        try:
            t.join()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
