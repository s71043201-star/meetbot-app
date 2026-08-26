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
    # 跨行整批匯款手續費(每筆);富邦行內互轉免手續費,僅非富邦扣此費,由收款人負擔
    "CROSS_BANK_FEE": 30,
    # 每份處方費 / 每份執行費 / 每人次處置費
    "FEE_PER_PRESCRIPTION": 300,
    "FEE_PER_EXECUTION": 100,
    # 處置費：一般實體課程的費率,同時也是「執行課程」對不到任何規則時的預設
    "FEE_PER_TREATMENT": 400,
    # 處置費費率分流：比對處方紀錄 Excel「執行課程」+「執行單位」兩欄的文字,
    # 由上而下比,第一個命中 keywords 的規則決定該筆單價;都沒中 → 一般課程 400 元。
    # 關鍵字比對前會做全形轉半形 + 去空白 + 轉大寫,故 "plus 2"、"PLUS２" 皆可命中。
    # 實際資料裡兩種型態標在不同欄,所以兩欄一起比：
    #   PLUS2      → 「執行課程」如 "PLUS2-0819富洲里-運動"
    #   線上微課程 → 「執行單位」= "線上微課程"(課程名稱看不出來)
    # 日後新增課程型態或改費率,只要改 config.json 的這個陣列。
    "TREATMENT_FEE_RULES": [
        {"label": "處方PLUS2", "fee": 200, "keywords": ["PLUS2", "PLUS 2"]},
        {"label": "線上微課程", "fee": 100,
         "keywords": ["線上微課程", "視訊", "遠距"]},
    ],
    "TREATMENT_FEE_DEFAULT_LABEL": "一般實體課程",
    # 線上(視訊)課清單 — 與處方儀表板同一份定義：課程管理裡
    # delivery_mode != 'offline' 的課(YouTube 15 分鐘影片課)。
    # 這些課的「執行單位」填的是講師所屬實體單位(士林社大、癌症關懷基金會…),
    # 從單位完全看不出是線上課,只有課名認得出來,所以一定要比對課名。
    # 比對前會去掉課名開頭的數字(課務每天會在課名前加數字)、去空白、轉小寫,
    # 與儀表板 course_slot_stats.online_name_map 的正規化規則一致。
    # 課程有新增/下架時,用 scripts/sync_online_courses.py 重新同步這份清單。
    "ONLINE_COURSE_NAMES": [
        "1⾃律神經調節法 : 15分鐘迅速告別焦慮",
        "1外食也能吃健康：便當店與超商的聰明選擇",
        "1居家全齡肌力",
        "1美麗禪繞畫",
        "2【香氣音療】身心共振放鬆處方",
        "2太極有氧(Tai Chi Synergy)",
        "2綠色療癒與社交",
        "2腸道好，人不老，打造全齡免疫的腸腦軸線",
        "3只要一句話讓你開心玩日本",
        "3居家彼拉提斯",
        "3打開食品黑盒子",
        "3舒心粉彩輕鬆畫",
        "4控糖大作戰：低GI 如何對抗身體慢性發炎",
        "4漢方有氧_萬馬奔騰",
        "4破解失眠惡性循環，三招找回自然好眠",
        "4輕鬆學，AI成專屬顧問",
    ],
    # 扣繳設定（二代健保採「達(含)」>=；所得稅採「超過」>）
    "NHI_RATE": 0.0211,            # 二代健保補充保費率
    # 所得稅就源扣繳：依報稅類別分開（執行業務 vs 薪資）
    #   執行業務所得：10%，單次給付 > 20,000 才扣（剛好 20,000 稅額 2,000，依免扣門檻免扣）
    "INCOME_TAX_RATE": 0.10,       # 執行業務所得稅率（沿用原 key，相容既有 config.json）
    "INCOME_TAX_THRESHOLD": 20000, # 執行業務：給付 > 此值才扣
    #   薪資所得：5%，單次給付未達當年度薪資扣繳稅額表起扣標準（115 年 90,500 元，不含）
    #            則不扣；超過才預扣 5%
    "INCOME_TAX_RATE_SALARY": 0.05,        # 薪資所得稅率
    "INCOME_TAX_THRESHOLD_SALARY": 90500,  # 薪資：給付 > 此值才扣（起扣標準，不含）
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
CROSS_BANK_FEE: int = _CFG["CROSS_BANK_FEE"]
FEE_PER_PRESCRIPTION: int = _CFG["FEE_PER_PRESCRIPTION"]
FEE_PER_EXECUTION: int = _CFG["FEE_PER_EXECUTION"]
FEE_PER_TREATMENT: int = _CFG["FEE_PER_TREATMENT"]
TREATMENT_FEE_RULES: list = _CFG["TREATMENT_FEE_RULES"]
TREATMENT_FEE_DEFAULT_LABEL: str = _CFG["TREATMENT_FEE_DEFAULT_LABEL"]
ONLINE_COURSE_NAMES: list = _CFG["ONLINE_COURSE_NAMES"]
NHI_RATE: float = _CFG["NHI_RATE"]
INCOME_TAX_RATE: float = _CFG["INCOME_TAX_RATE"]
INCOME_TAX_THRESHOLD: int = _CFG["INCOME_TAX_THRESHOLD"]
INCOME_TAX_RATE_SALARY: float = _CFG["INCOME_TAX_RATE_SALARY"]
INCOME_TAX_THRESHOLD_SALARY: int = _CFG["INCOME_TAX_THRESHOLD_SALARY"]
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
