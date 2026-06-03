"""扣繳規則邊界測試（純標準庫，免裝 pytest）。

跑法:
    python test_tax_rules.py

重點守住兩個「臨界值」行為，避免日後又把二代健保改回嚴格大於：
  - 二代健保採「達門檻（含）」＝大於等於：剛好達標也要扣。
  - 所得稅採「超過門檻」＝嚴格大於：給付剛好 20,000 不扣
    （稅額 2,000，依「應扣繳稅額不超過 2,000 免扣」）。
"""
import sys

from tax_rules import withhold, PRACTICE, SALARY
from config import (
    NHI_RATE, INCOME_TAX_RATE, INCOME_TAX_THRESHOLD,
    NHI_THRESHOLD_PRACTICE, NHI_THRESHOLD_SALARY,
)

# (gross, category, 期望二代健保, 期望所得稅, 說明)
CASES = [
    # ── 執業所得：二代健保門檻 20,000 ──
    (19999, PRACTICE, 0, 0, "未達門檻：都不扣"),
    (20000, PRACTICE, round(20000 * NHI_RATE), 0,
     "剛好達二代健保門檻(含)→扣健保；所得稅剛好20000不扣"),
    (20001, PRACTICE, round(20001 * NHI_RATE), round(20001 * INCOME_TAX_RATE),
     "超過門檻：兩者都扣"),
    # ── 薪資：二代健保門檻 29,500（基本薪資）──
    (29499, SALARY, 0, round(29499 * INCOME_TAX_RATE),
     "未達薪資健保門檻不扣健保；已超過所得稅門檻要扣稅"),
    (29500, SALARY, round(29500 * NHI_RATE), round(29500 * INCOME_TAX_RATE),
     "剛好達薪資健保門檻(含)→扣健保"),
    # ── 防呆 ──
    (0, PRACTICE, 0, 0, "零給付"),
    (None, PRACTICE, 0, 0, "None 給付當 0"),
]


def main() -> int:
    # 門檻值前提（若 config 被改動，測試的期望值需一併檢視）
    assert NHI_THRESHOLD_PRACTICE == 20000, NHI_THRESHOLD_PRACTICE
    assert NHI_THRESHOLD_SALARY == 29500, NHI_THRESHOLD_SALARY
    assert INCOME_TAX_THRESHOLD == 20000, INCOME_TAX_THRESHOLD

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
    if failures:
        print(f"{failures} 個測試未通過")
        return 1
    print(f"全部 {len(CASES)} 個測試通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
