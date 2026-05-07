"""診所分區名單管理。

從同目錄下的「診所分區.xlsx」讀取 3 個分頁（北投/士林/中山），
每個分頁的 A 欄由第 2 列開始列出該區診所名稱。

匹配規則：
  1. 精確相同
  2. 子字串（雙向）
  3. 最長共同前綴 ≥ 3 字
（與 app.py 的 _match_clinic 同邏輯，確保跨模組一致。）
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

import openpyxl


REGION_NAMES: List[str] = ["北投", "士林", "中山"]


def load_regions(xlsx_path: str) -> Dict[str, List[str]]:
    """讀取 Excel，回傳 {區名: [診所名…]}。檔案不存在則回傳空 dict。"""
    result: Dict[str, List[str]] = {r: [] for r in REGION_NAMES}
    if not xlsx_path or not os.path.isfile(xlsx_path):
        return result

    try:
        wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    except Exception:
        return result

    for region in REGION_NAMES:
        if region not in wb.sheetnames:
            continue
        ws = wb[region]
        names: List[str] = []
        for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
            v = row[0] if row else None
            if v is None:
                continue
            name = str(v).strip()
            if name:
                names.append(name)
        result[region] = names

    wb.close()
    return result


def find_region(
    clinic_name: str,
    regions: Dict[str, List[str]],
) -> Optional[str]:
    """依序嘗試精確 → 子字串 → 最長共同前綴，回傳分區名或 None。"""
    if not clinic_name:
        return None

    # 1. 精確相同
    for region, clinics in regions.items():
        if clinic_name in clinics:
            return region

    # 2. 子字串（雙向）
    for region, clinics in regions.items():
        for name in clinics:
            if name and (name in clinic_name or clinic_name in name):
                return region

    # 3. 最長共同前綴（≥3 字）
    best_region: Optional[str] = None
    best_len = 0
    for region, clinics in regions.items():
        for name in clinics:
            if not name:
                continue
            prefix_len = 0
            for a, b in zip(clinic_name, name):
                if a == b:
                    prefix_len += 1
                else:
                    break
            if prefix_len >= 3 and prefix_len > best_len:
                best_len = prefix_len
                best_region = region

    return best_region


def create_template(xlsx_path: str) -> None:
    """建立空白診所分區 Excel 範本：3 分頁，各分頁 A 欄標題「診所名稱」。"""
    wb = openpyxl.Workbook()
    # 移除預設 Sheet，改用 REGION_NAMES 當分頁
    default = wb.active
    for i, region in enumerate(REGION_NAMES):
        if i == 0:
            default.title = region
            ws = default
        else:
            ws = wb.create_sheet(title=region)
        ws["A1"] = "診所名稱"

    wb.save(xlsx_path)
