"""扣繳規則邊界測試（純標準庫，免裝 pytest）。

跑法:
    python test_tax_rules.py

重點守住臨界值行為：
  - 二代健保採「達門檻（含）」＝大於等於：剛好達標也要扣。
  - 所得稅採「超過門檻」＝嚴格大於，且依類別不同：
    執業所得 10%（給付剛好 20,000 不扣，稅額 2,000 依免扣門檻免扣）；
    薪資 5%（給付剛好 90,500 起扣標準「不含」不扣，超過才扣）。
"""
import sys

from tax_rules import withhold, category_for, PRACTICE, SALARY
from config import (
    NHI_RATE, INCOME_TAX_RATE, INCOME_TAX_THRESHOLD,
    INCOME_TAX_RATE_SALARY, INCOME_TAX_THRESHOLD_SALARY,
    NHI_THRESHOLD_PRACTICE, NHI_THRESHOLD_SALARY,
)

# (gross, category, 期望二代健保, 期望所得稅, 說明)
CASES = [
    # ── 執業所得：二代健保門檻 20,000；所得稅 10%、>20,000 ──
    (19999, PRACTICE, 0, 0, "未達門檻：都不扣"),
    (20000, PRACTICE, round(20000 * NHI_RATE), 0,
     "剛好達二代健保門檻(含)→扣健保；所得稅剛好20000不扣"),
    (20001, PRACTICE, round(20001 * NHI_RATE), round(20001 * INCOME_TAX_RATE),
     "超過門檻：兩者都扣（所得稅10%）"),
    # ── 薪資：二代健保門檻 29,500；所得稅 5%、起扣標準 90,500（不含）──
    (29499, SALARY, 0, 0,
     "未達薪資健保門檻(29,500)不扣健保；未達薪資所得稅起扣(90,500)不扣稅"),
    (29500, SALARY, round(29500 * NHI_RATE), 0,
     "剛好達薪資健保門檻(含)→扣健保；未達90,500不扣稅"),
    (90500, SALARY, round(90500 * NHI_RATE), 0,
     "剛好等於起扣標準90,500(不含)→不扣稅"),
    (90501, SALARY, round(90501 * NHI_RATE),
     round(90501 * INCOME_TAX_RATE_SALARY),
     "超過90,500→預扣5%薪資所得稅"),
    # ── 防呆 ──
    (0, PRACTICE, 0, 0, "零給付"),
    (None, PRACTICE, 0, 0, "None 給付當 0"),
]


# (occupation, role, 期望類別, 說明) — 報稅類別歸類（category_for）
CATEGORY_CASES = [
    ("營養師", "課程老師", PRACTICE, "營養師 → 執業所得"),
    ("心理師", "課程老師", PRACTICE, "心理師 → 執業所得"),
    ("臨床心理師", "課程老師", PRACTICE, "臨床心理師 → 執業所得"),
    ("諮商心理師", "課程老師", PRACTICE, "諮商心理師 → 執業所得"),
    ("藥師", "課程老師", PRACTICE, "藥師 → 執業所得"),
    ("運動教練", "課程老師", SALARY, "運動教練 → 薪資"),
    ("", "課程老師", SALARY, "身分別空白的課程老師 → 預設薪資"),
    ("瑜珈老師", "課程老師", SALARY, "清單外職稱的課程老師 → 預設薪資"),
    ("", "醫師", PRACTICE, "醫師角色 → 執業所得"),
    ("", "診所行政人員", SALARY, "診所行政 → 薪資（固定7000不扣，僅備查）"),
]


def check_categories() -> int:
    failures = 0
    for occ, role, exp, note in CATEGORY_CASES:
        got = category_for(occ, role)
        ok = got == exp
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] occ={occ or '(空)':<6} role={role:<8} → {got}  — {note}")
        if not ok:
            failures += 1
            print(f"        期望 {exp}")
    return failures


def main() -> int:
    # 門檻值前提（若 config 被改動，測試的期望值需一併檢視）
    assert NHI_THRESHOLD_PRACTICE == 20000, NHI_THRESHOLD_PRACTICE
    assert NHI_THRESHOLD_SALARY == 29500, NHI_THRESHOLD_SALARY
    assert INCOME_TAX_THRESHOLD == 20000, INCOME_TAX_THRESHOLD
    assert INCOME_TAX_THRESHOLD_SALARY == 90500, INCOME_TAX_THRESHOLD_SALARY
    assert INCOME_TAX_RATE_SALARY == 0.05, INCOME_TAX_RATE_SALARY

    failures = 0
    for gross, cat, exp_nhi, exp_tax, note in CASES:
        nhi, tax, net = withhold(gross, cat)
        g = int(gross or 0)
        exp_net = g - exp_nhi - exp_tax
        ok = (nhi, tax, net) == (exp_nhi, exp_tax, exp_net)
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {g:>6} {cat}: "
              f"健保={nhi} 稅={tax} 實付={net}  — {note}")
        if not ok:
            failures += 1
            print(f"        期望 健保={exp_nhi} 稅={exp_tax} 實付={exp_net}")

    print("-" * 50)
    failures += check_categories()

    print("-" * 50)
    total = len(CASES) + len(CATEGORY_CASES)
    if failures:
        print(f"{failures} 個測試未通過")
        return 1
    print(f"全部 {total} 個測試通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
