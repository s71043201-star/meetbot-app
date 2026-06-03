"""台灣就源扣繳規則（集中管理，供領據與富邦匯款/報稅檔共用）

規則（費率與門檻可由 config.json 覆蓋）：
  二代健保補充保費（NHI_RATE，預設 2.11%）— 門檻採「達（含）」＝大於等於：
    執業所得：單次給付 >= NHI_THRESHOLD_PRACTICE（預設 20,000）才扣
    薪資    ：單次給付 >= NHI_THRESHOLD_SALARY  （預設 29,500 基本薪資）才扣
  所得稅（INCOME_TAX_RATE，預設 10%）— 門檻採「超過」＝嚴格大於：
    單次給付 > INCOME_TAX_THRESHOLD（預設 20,000）才扣（不分類別）
    （給付剛好 20,000 時稅額 2,000，依「應扣繳稅額不超過 2,000 免扣」免扣）

報稅類別（第三頁 H 欄對照）：
  執業所得：醫師、營養師、藥師
  薪資    ：護理師、運動教練、大學/社大老師

實務上需要靠「身分別」區分的只有營養師（個資檔中與課程老師混在一起）：
  - 醫師（角色）一律執業所得。
  - 課程老師（角色）：身分別＝營養師 → 執業所得；其餘（運動教練/老師/空白）→ 薪資。
  - 診所行政人員：固定 7000，不會達門檻、不扣稅，故毋須註記身分別。
"""

from config import (
    NHI_RATE, INCOME_TAX_RATE, INCOME_TAX_THRESHOLD,
    NHI_THRESHOLD_PRACTICE, NHI_THRESHOLD_SALARY,
)

PRACTICE = "執業所得"
SALARY = "薪資"

# 身分別/職業 → 報稅類別
OCCUPATION_CATEGORY = {
    "醫師": PRACTICE,
    "營養師": PRACTICE,
    "藥師": PRACTICE,
    "護理師": SALARY,
    "運動教練": SALARY,
    "大學/社大老師": SALARY,
    "大學老師": SALARY,
    "社大老師": SALARY,
    "老師": SALARY,
    "課程老師": SALARY,   # 身分別若直接填「課程老師」即薪資（非營養師者）
}


def category_for(occupation: str = "", role: str = "") -> str:
    """依身分別（職業）決定報稅類別；無法判定時退而求其次依角色，
    再不行預設執業所得（門檻較低、較保守）。
    """
    occ = (occupation or "").strip()
    if occ:
        if occ in OCCUPATION_CATEGORY:
            return OCCUPATION_CATEGORY[occ]
        for kw, cat in OCCUPATION_CATEGORY.items():
            if kw in occ or occ in kw:
                return cat
    # 身分別空白或無法判定 → 依角色（課程老師/診所行政＝薪資；醫師＝執業所得）
    if role in ("課程老師", "診所行政人員"):
        return SALARY
    return PRACTICE


def nhi_threshold(category: str) -> int:
    return NHI_THRESHOLD_SALARY if category == SALARY else NHI_THRESHOLD_PRACTICE


def withhold(gross, category: str):
    """回傳 (二代健保, 所得稅, 實付)。

    二代健保：達門檻（含）即扣（>=）；所得稅：超過門檻才扣（>）。
    """
    g = int(gross or 0)
    # 二代健保：法規為「達門檻（含）」→ 大於等於才扣（20,000 剛好達標也要扣）。
    nhi = round(g * NHI_RATE) if g >= nhi_threshold(category) else 0
    # 所得稅：給付剛好 20,000 時稅額 2,000，依「應扣繳稅額不超過 2,000 免扣」免扣，
    # 故維持嚴格大於（> 20,000 才扣）。
    income_tax = round(g * INCOME_TAX_RATE) if g > INCOME_TAX_THRESHOLD else 0
    return nhi, income_tax, g - nhi - income_tax
