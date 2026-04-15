"""產生範例 Excel 檔供測試"""

import openpyxl
from openpyxl.styles import Font

wb = openpyxl.Workbook()

# === Sheet 1: 基本資料 ===
ws = wb.active
ws.title = "基本資料"
ws["A1"] = "申報年度"
ws["B1"] = 115
ws["A2"] = "申報月份"
ws["B2"] = 3
for cell in ["A1", "A2"]:
    ws[cell].font = Font(bold=True)

# === Sheet 2: 處方統計 ===
ws = wb.create_sheet("處方統計")
headers = ["醫療機構", "開立醫師",
           "運動處方(開立)", "營養處方(開立)", "情緒調適處方(開立)", "社會處方(開立)",
           "運動處方(執行)", "營養處方(執行)", "情緒調適處方(執行)", "社會處方(執行)"]
for i, h in enumerate(headers, 1):
    ws.cell(1, i, h).font = Font(bold=True)

# 範例資料：3 位醫師
data = [
    ["何叔芳小兒科診所", "何叔芳", 6, 6, 6, 6, 4, 5, 3, 3],
    ["台北欣安耳鼻喉科", "李政璋", 32, 32, 32, 32, 7, 2, 1, 3],
    ["慧捷診所", "李進良", 5, 5, 5, 5, 3, 6, 3, 3],
]
for r, row_data in enumerate(data, 2):
    for c, val in enumerate(row_data, 1):
        ws.cell(r, c, val)

# === Sheet 3: 健康管理費 ===
ws = wb.create_sheet("健康管理費")
headers = ["醫療機構", "診所人員", "開立處方人數", "開立份數", "是否達標"]
for i, h in enumerate(headers, 1):
    ws.cell(1, i, h).font = Font(bold=True)
data = [
    ["何叔芳小兒科診所", "何叔芳", 6, 24, True],
    ["台北欣安耳鼻喉科", "李政璋", 32, 128, True],
    ["慧捷診所", "李進良", 5, 20, True],
]
for r, row_data in enumerate(data, 2):
    for c, val in enumerate(row_data, 1):
        ws.cell(r, c, val)

# === Sheet 4: 民眾明細 ===
ws = wb.create_sheet("民眾明細")
headers = ["民眾姓名", "身分證字號", "出生年月日", "處方人員姓名"]
for i, h in enumerate(headers, 1):
    ws.cell(1, i, h).font = Font(bold=True)
data = [
    ["王大明", "A123456789", "1960/05/15", "何叔芳"],
    ["李小華", "B234567890", "1972/08/20", "何叔芳"],
    ["張美玲", "C345678901", "1965/03/10", "李政璋"],
    ["陳志明", "D456789012", "1958/11/25", "李政璋"],
    ["林淑芬", "E567890123", "1970/07/03", "李進良"],
]
for r, row_data in enumerate(data, 2):
    for c, val in enumerate(row_data, 1):
        ws.cell(r, c, val)

# === Sheet 5: 領據資訊（診所端）===
ws = wb.create_sheet("領據資訊")
headers = ["具領人", "身分證字號", "戶籍地址", "聯絡電話",
           "戶名", "銀行及分行", "銀行代碼", "帳號", "金額"]
for i, h in enumerate(headers, 1):
    ws.cell(1, i, h).font = Font(bold=True)
ws.cell(2, 1, "蔡秉勳")
ws.cell(2, 2, "F678901234")
ws.cell(2, 3, "台北市大安區忠孝東路100號")
ws.cell(2, 4, "0912-345-678")
ws.cell(2, 5, "蔡秉勳")
ws.cell(2, 6, "台北富邦銀行 忠孝分行")
ws.cell(2, 7, "012")
ws.cell(2, 8, "123456789012")
ws.cell(2, 9, 122400)

# === Sheet 6: 執行人員 ===
ws = wb.create_sheet("執行人員")
headers = ["執行人員", "處方類型", "服務人次",
           "具領人", "身分證字號", "戶籍地址", "聯絡電話",
           "戶名", "銀行及分行", "銀行代碼", "帳號"]
for i, h in enumerate(headers, 1):
    ws.cell(1, i, h).font = Font(bold=True)
data = [
    ["何叔芳", "運動處方", 8,
     "何叔芳", "G789012345", "台北市信義區松仁路50號", "0922-111-222",
     "何叔芳", "國泰世華銀行 信義分行", "013", "987654321098"],
    ["李政璋", "營養處方", 15,
     "李政璋", "H890123456", "台北市中山區南京東路200號", "0933-222-333",
     "李政璋", "中國信託銀行 中山分行", "822", "111222333444"],
]
for r, row_data in enumerate(data, 2):
    for c, val in enumerate(row_data, 1):
        ws.cell(r, c, val)

# 自動調整欄寬
for ws in wb.worksheets:
    for col in ws.columns:
        max_length = 0
        col_letter = col[0].column_letter
        for cell in col:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = min(max_length + 4, 30)

wb.save("C:/Users/s7104/OneDrive/code/health-plan-docx-generator/sample_data.xlsx")
print("sample_data.xlsx 已建立")
