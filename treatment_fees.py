"""處方處置費費率 — 依「執行課程」欄文字分流

核銷新規定後,處置費不再一律 400 元/人次,而是看執行的課程型態:
  - 處方PLUS2 活動：每筆執行給付 200 元
  - 視訊課程：      每筆執行     100 元
  - 其餘(一般實體課程)：沿用 FEE_PER_TREATMENT(400 元)

計數單位仍是「每筆執行紀錄一筆」,只有單價依課程型態不同。

判斷依據 = 處方紀錄 Excel 的「執行課程」(第 16 欄) + 「執行單位」(第 13 欄):

  1. PLUS2  → 課名(或單位)含 "PLUS2",如 "PLUS2-0819富洲里-運動"
  2. 視訊   → 課名比對「線上課清單」(config 的 ONLINE_COURSE_NAMES)
  3. 其餘   → 一般課程

視訊一定要比對課名,不能只看執行單位:線上課的「執行單位」填的是講師所屬的
實體單位(士林社區大學、癌症關懷基金會、中國文化大學…),從單位完全看不出是
線上課。實測 8,076 筆裡只看單位會把 3,965 筆線上課誤算成 400 元。

線上課清單與處方儀表板(tpma-statistics)同一份定義 —— 課程管理裡
delivery_mode != 'offline' 的課(YouTube 15 分鐘影片課)。課名比對前要
去掉開頭數字(課務每天會在課名前加數字,如 "1居家全齡肌力"/"3居家彼拉提斯")、
去空白、轉小寫,與儀表板 course_slot_stats.online_name_map 的正規化一致。

比對規則放在 config.json,不用改程式、不用重打包 exe:
  TREATMENT_FEE_RULES  費率與關鍵字(關鍵字規則仍保留,當課名清單的補漏)
  ONLINE_COURSE_NAMES  線上課清單(課程增減時用 scripts/sync_online_courses.py 更新)
"""

from __future__ import annotations

import unicodedata
from typing import Dict, List

import re

from config import (
    FEE_PER_TREATMENT,
    TREATMENT_FEE_RULES,
    TREATMENT_FEE_DEFAULT_LABEL,
    ONLINE_COURSE_NAMES,
)

# 線上(視訊)課的費率標籤 — 課名命中 ONLINE_COURSE_NAMES 時採用
ONLINE_LABEL = "線上微課程"

DEFAULT_LABEL: str = TREATMENT_FEE_DEFAULT_LABEL


def _norm(text) -> str:
    """正規化課程名稱,讓 'plus 2'、'PLUS２'、'ＰＬＵＳ2' 都能命中同一關鍵字。

    NFKC 把全形轉半形,再去掉所有空白並轉大寫。
    """
    s = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(s.split()).upper()


def course_key(name) -> str:
    """課名正規化 — 去掉開頭數字前綴 → 去空白 → 轉小寫。

    課務每天會在課名前加數字("1居家全齡肌力"、"3居家彼拉提斯"),不去掉會
    比對不到。與處方儀表板 course_slot_stats.online_name_map 同一套規則
    (已驗證 16/16 完全重現)。
    """
    s = re.sub(r"^\d+", "", str(name or ""))
    return "".join(s.split()).lower()


def _online_keys() -> set:
    return {course_key(n) for n in (ONLINE_COURSE_NAMES or []) if course_key(n)}


_ONLINE_KEYS = _online_keys()


def is_online_course(course_text) -> bool:
    """課名是否屬於線上(視訊)課清單"""
    k = course_key(course_text)
    return bool(k) and k in _ONLINE_KEYS


def classify_course(course_text, unit_text="") -> str:
    """歸類成費率標籤(處方PLUS2 / 視訊課程 / 一般課程)。

    course_text: 「執行課程」欄 — PLUS2 與線上課都靠這欄認
    unit_text:   「執行單位」欄 — 只當關鍵字規則的補充比對

    順序：PLUS2 關鍵字 → 線上課清單 → 其他關鍵字規則 → 一般課程。
    PLUS2 先比,因為 PLUS2 活動的課名不會出現在線上課清單裡,兩者不衝突;
    先比 PLUS2 可確保未來即使有同名課也不會被誤判成線上課。
    """
    norm = _norm(course_text) + " " + _norm(unit_text)

    # 1) PLUS2（或 config 裡排在線上課之前的其他規則）
    for rule in TREATMENT_FEE_RULES:
        if rule.get("label") == ONLINE_LABEL:
            continue
        for kw in rule.get("keywords", ()):
            nk = _norm(kw)
            if nk and nk in norm:
                return rule.get("label") or DEFAULT_LABEL

    # 2) 線上課清單（主要判準）
    if is_online_course(course_text):
        return ONLINE_LABEL

    # 3) 線上課的關鍵字補漏（清單還沒更新、但單位/課名已標明線上時）
    for rule in TREATMENT_FEE_RULES:
        if rule.get("label") != ONLINE_LABEL:
            continue
        for kw in rule.get("keywords", ()):
            nk = _norm(kw)
            if nk and nk in norm:
                return ONLINE_LABEL

    return DEFAULT_LABEL


def fee_for_label(label: str) -> int:
    """費率標籤 → 每筆單價(元)。未知標籤退回一般課程費率。"""
    for rule in TREATMENT_FEE_RULES:
        if rule.get("label") == label:
            try:
                return int(rule.get("fee", FEE_PER_TREATMENT))
            except (TypeError, ValueError):
                return FEE_PER_TREATMENT
    return FEE_PER_TREATMENT


def fee_for_course(course_text, unit_text="") -> int:
    """「執行課程」+「執行單位」→ 每筆單價(元)"""
    return fee_for_label(classify_course(course_text, unit_text))


def ordered_labels() -> List[str]:
    """固定顯示順序:一般課程 → config 規則的順序(PLUS2 → 視訊課程)。

    領據 pivot 表、核銷總表都照這個順序列,同一位執行人員每月版面一致。
    """
    labels = [DEFAULT_LABEL]
    for rule in TREATMENT_FEE_RULES:
        lb = rule.get("label")
        if lb and lb not in labels:
            labels.append(lb)
    return labels


def fee_map() -> Dict[str, int]:
    """{費率標籤: 單價} — 供領據/總表一次取用"""
    return {lb: fee_for_label(lb) for lb in ordered_labels()}


def row_label(label: str) -> str:
    """領據 pivot 表 / 總表的列標籤文字,含單價以便核銷對帳。

    例:「處方處置費－處方PLUS2(200元)」
    只有一種費率在跑時(如舊資料全歸一般課程)由呼叫端決定要不要簡化。
    """
    return f"處方處置費－{label}({fee_for_label(label)}元)"


def total_amount(course_counts: Dict[str, Dict[str, int]]) -> int:
    """{費率標籤: {處方類型: 人次}} → 申報總金額"""
    total = 0
    for label, per_type in (course_counts or {}).items():
        unit = fee_for_label(label)
        total += sum(per_type.values()) * unit
    return total
