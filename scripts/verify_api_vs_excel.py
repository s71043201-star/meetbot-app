"""對帳：backend API 抓的資料 vs 手動匯出的 Excel

用途：在把產生器切換成「直接抓 API」之前，先確認兩邊算出來的東西一模一樣。
逐筆比對欄位，再比對統計結果（執行人員數、費率分類、金額）。

前置：secrets.json 要填好 RX_ACCOUNT / RX_PASSWORD（格式見 secrets.json.example）。

用法：
    python scripts/verify_api_vs_excel.py <執行用的Excel> [起日 迄日]

    起迄日預設取 Excel 檔名裡的區間（prescription_report_YYYY-MM-DD_YYYY-MM-DD.xlsx）。

例：
    python scripts/verify_api_vs_excel.py "C:/.../prescription_report_2026-08-01_2026-08-26 (3).xlsx"
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import openpyxl

import backend_api as api
from reader import read_prescription_report
from treatment_fees import classify_course, fee_for_label

COL_NAMES = [
    "流水號", "姓名", "性別", "生日", "身分證字號", "手機", "處方類型",
    "開立診所", "開立醫師", "是否選課", "選課名稱", "選課時段", "執行單位",
    "執行人員", "執行處方", "執行課程", "執行日期", "處方費", "處方執行費",
    "處方處置費", "已核銷", "開立日期時間",
]


def load_excel_rows(path: str) -> list:
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["處方紀錄"]
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] is not None]
    wb.close()
    return rows


def dates_from_name(path: str):
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})", os.path.basename(path))
    return (m.group(1), m.group(2)) if m else (None, None)


def stats(rows, label):
    """用同一套 reader 邏輯算統計，兩邊才可比"""
    data = read_prescription_report(
        report_year=115, report_month=8,
        issuance_rows=rows, execution_rows=rows)
    tot = Counter()
    for ex in data.executors:
        for lb, d in ex.course_counts.items():
            tot[lb] += sum(d.values())
    amount = sum(e.receipt.amount for e in data.executors if e.receipt)
    print(f"\n[{label}]")
    print(f"  執行人員 {len(data.executors)} 位、處置費合計 {amount:,} 元")
    for lb in sorted(tot):
        print(f"    {lb:8} {tot[lb]:5} 筆 × {fee_for_label(lb):>3} = {tot[lb]*fee_for_label(lb):>9,}")
    return {"executors": len(data.executors), "amount": amount, "by_label": dict(tot)}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    xlsx = sys.argv[1]
    if len(sys.argv) >= 4:
        start, end = sys.argv[2], sys.argv[3]
    else:
        start, end = dates_from_name(xlsx)
    if not start:
        print("無法從檔名判斷區間，請手動指定起迄日")
        return 2

    try:
        print(api.check_connection())
    except api.RxApiError as e:
        print("X " + str(e))
        print("")
        print("最省事的設定方式：")
        print("    python scripts/set_rx_credentials.py")
        return 2
    print(f"對帳區間：{start} ～ {end}\n")

    excel_rows = load_excel_rows(xlsx)
    print(f"Excel：{len(excel_rows)} 筆")

    try:
        api_rows = api.fetch_rows(start, end, api.FEE_KEY_TREATMENT,
                                  api.DATE_FIELD_EXEC,
                                  progress=lambda m: print("  " + m))
    except api.RxApiError as e:
        print("X 查詢失敗：" + str(e))
        print("  若帳密正確，多半是該帳號沒有核銷管理的查詢權限。")
        return 2
    print(f"API  ：{len(api_rows)} 筆")

    # --- 逐筆比對（以流水號對齊）---
    e_by = {str(r[0]): r for r in excel_rows}
    a_by = {str(r[0]): r for r in api_rows}
    only_e = sorted(set(e_by) - set(a_by))
    only_a = sorted(set(a_by) - set(e_by))
    print(f"\n只在 Excel：{len(only_e)} 筆　只在 API：{len(only_a)} 筆")
    for k in only_e[:5]:
        print(f"    Excel only {k} 執行日={e_by[k][16]}")
    for k in only_a[:5]:
        print(f"    API   only {k} 執行日={a_by[k][16]}")

    diff_cols = Counter()
    samples = {}
    for k in sorted(set(e_by) & set(a_by)):
        er, ar = e_by[k], a_by[k]
        for i in range(min(len(er), len(ar), len(COL_NAMES))):
            ev = "" if er[i] is None else str(er[i]).strip()
            av = "" if ar[i] is None else str(ar[i]).strip()
            if ev != av:
                diff_cols[COL_NAMES[i]] += 1
                samples.setdefault(COL_NAMES[i], (k, ev, av))
    print(f"\n共同 {len(set(e_by) & set(a_by))} 筆，欄位不一致統計：")
    if not diff_cols:
        print("    完全一致 ✓")
    for c, n in diff_cols.most_common():
        k, ev, av = samples[c]
        print(f"    {c:10} {n:5} 筆  例[{k}] Excel={ev[:28]!r} API={av[:28]!r}")

    # --- 統計結果比對 ---
    # 判定看「共同筆」：Excel 是匯出當下的快照，API 抓的是此刻最新，兩者筆數
    # 本來就會差（當天後來又新增的執行紀錄）。那不是邏輯錯誤，只有「同一批
    # 紀錄算出不同結果」才是。
    common = sorted(set(e_by) & set(a_by))
    s_ec = stats([e_by[k] for k in common], "共同筆 · Excel")
    s_ac = stats([a_by[k] for k in common], "共同筆 · API")
    same = s_ec == s_ac

    stats(api_rows, "API 全量（此刻最新，含 Excel 匯出後新增的紀錄）")

    print("\n" + "=" * 52)
    if same and not only_e:
        print("對帳通過 ✓ 同一批紀錄兩邊算出的結果完全相同")
        if only_a:
            newest = max(str(a_by[k][16] or "") for k in only_a)
            print(f"  API 另有 {len(only_a)} 筆是 Excel 匯出後才新增的"
                  f"（最新到 {newest}），屬正常時間差")
        print("  可以切換成直接抓 API")
        return 0
    if only_e:
        print(f"對帳未過 X Excel 有 {len(only_e)} 筆 API 抓不到 —— "
              "查詢參數或區間可能不對")
    else:
        print("對帳未過 X 同一批紀錄算出不同結果，查上面的欄位差異")
    return 1


if __name__ == "__main__":
    sys.exit(main())
