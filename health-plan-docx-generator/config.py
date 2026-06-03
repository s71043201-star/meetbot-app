"""集中管理可調整的參數 / 費用。

執行時順序:
  1. 先載入本檔預設值
  2. 若 exe 同目錄下有 config.json,以 JSON 內容覆蓋（公開設定）
  3. 若 exe 同目錄下有 secrets.json,再以其內容覆蓋（私密設定，
     不入 git；用於 Google Drive URL、密碼等敏感值）

   PyInstaller onefile: exe 所在目錄 = sys.executable 的 parent,
   開發模式: 當前工作目錄

未來法規或費用調整 → 改 config.json 即可,不用重打包 exe。
雲端 URL / 密碼變更 → 改 secrets.json，不會被 push 到 GitHub。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---- Defaults --------------------------------------------------------
_DEFAULTS: dict = {
    # 健管費:達標的診所可申報
    "HEALTH_MGMT_FEE": 7000,
    # 每份處方費 / 每份執行費 / 每人次處置費
    "FEE_PER_PRESCRIPTION": 300,
    "FEE_PER_EXECUTION": 100,
    "FEE_PER_TREATMENT": 400,
    # 扣繳設定（二代健保採「達(含)」>=；所得稅採「超過」>）
    "NHI_RATE": 0.0211,            # 二代健保補充保費率
    "INCOME_TAX_RATE": 0.10,       # 所得稅就源扣繳率
    "INCOME_TAX_THRESHOLD": 20000, # 所得稅：給付 > 此值才扣（不分類別）
    "NHI_THRESHOLD_PRACTICE": 20000,  # 二代健保門檻：執業所得（給付 >= 此值即扣）
    "NHI_THRESHOLD_SALARY": 29500,    # 二代健保門檻：薪資（給付 >= 此值即扣）
    # 份數 ÷ 此值 = 對應人數門檻(註解顯示用)
    "PEOPLE_DIVISOR": 4,
    # UI「健管費最低份數」欄位預設值
    "MIN_PRESCRIPTIONS_DEFAULT": 20,
    # Google Drive 同步：診所分區（公開設定，非個資）
    "REGIONS_DRIVE_URL": "https://docs.google.com/spreadsheets/d/1i3hFvFBkwgemjz3W7IICXBy-Hc9Dd4-m/edit?usp=sharing",
    # 以下為敏感值，預設留空；實際值放 secrets.json（不入 git）
    "PEOPLE_DB_DRIVE_URL": "",
    "PEOPLE_DB_PASSWORD": "",
}


def _external_dir() -> Path:
    """決定 config.json / secrets.json 擺在哪。
    PyInstaller onefile: exe 解壓後 sys.executable 指向真正 exe 路徑。
    開發模式: sys.executable 是 python.exe,用 config.py 所在處。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _external_config_path() -> Path:
    return _external_dir() / "config.json"


def _external_secrets_path() -> Path:
    return _external_dir() / "secrets.json"


def _load_overrides(path: Path, cfg: dict) -> None:
    """把 path 的 JSON 內容覆蓋到 cfg；只接受已知 keys。靜默失敗。"""
    if not path.is_file():
        return
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in data.items():
            if k in _DEFAULTS:
                cfg[k] = v
    except (OSError, json.JSONDecodeError):
        pass


def _load() -> dict:
    cfg = dict(_DEFAULTS)
    _load_overrides(_external_config_path(), cfg)
    _load_overrides(_external_secrets_path(), cfg)
    return cfg


_CFG = _load()

HEALTH_MGMT_FEE: int = _CFG["HEALTH_MGMT_FEE"]
FEE_PER_PRESCRIPTION: int = _CFG["FEE_PER_PRESCRIPTION"]
FEE_PER_EXECUTION: int = _CFG["FEE_PER_EXECUTION"]
FEE_PER_TREATMENT: int = _CFG["FEE_PER_TREATMENT"]
NHI_RATE: float = _CFG["NHI_RATE"]
INCOME_TAX_RATE: float = _CFG["INCOME_TAX_RATE"]
INCOME_TAX_THRESHOLD: int = _CFG["INCOME_TAX_THRESHOLD"]
NHI_THRESHOLD_PRACTICE: int = _CFG["NHI_THRESHOLD_PRACTICE"]
NHI_THRESHOLD_SALARY: int = _CFG["NHI_THRESHOLD_SALARY"]
PEOPLE_DIVISOR: int = _CFG["PEOPLE_DIVISOR"]
MIN_PRESCRIPTIONS_DEFAULT: int = _CFG["MIN_PRESCRIPTIONS_DEFAULT"]
REGIONS_DRIVE_URL: str = _CFG["REGIONS_DRIVE_URL"]
PEOPLE_DB_DRIVE_URL: str = _CFG["PEOPLE_DB_DRIVE_URL"]
PEOPLE_DB_PASSWORD: str = _CFG["PEOPLE_DB_PASSWORD"]


def config_source() -> str:
    """回傳目前設定從哪裡來(供 log / debug 顯示)。"""
    parts = []
    cp = _external_config_path()
    sp = _external_secrets_path()
    parts.append(str(cp) if cp.is_file() else "(no config.json)")
    parts.append(str(sp) if sp.is_file() else "(no secrets.json)")
    return " + ".join(parts)
