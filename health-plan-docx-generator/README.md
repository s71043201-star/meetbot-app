# 核銷文件產生器

健康台灣深耕計畫 — 台北市醫師公會核銷文件自動產生工具。

讀取處方紀錄 Excel,產出:
- 處方費 / 處方執行費 / 健康管理費 核銷總表(Word + PDF)
- 執行人員民眾明細表
- 執行人員、醫師個人領據(Word + PDF)
- 各項合併總表 / 個別核銷明細

---

## 給使用者(執行檔版本)

直接執行 `dist/核銷文件產生器.exe`。

### 調整費用 / 門檻

**不用重新打包**。開啟 `dist/config.json` 編輯數值即可,下次啟動生效:

```json
{
  "HEALTH_MGMT_FEE": 7000,         // 健管費金額
  "FEE_PER_PRESCRIPTION": 300,     // 每份處方費
  "FEE_PER_EXECUTION": 100,        // 每份處方執行費
  "FEE_PER_TREATMENT": 400,        // 每人次處置費
  "PEOPLE_DIVISOR": 4,             // 份數 ÷ 此值 = 人數門檻
  "MIN_PRESCRIPTIONS_DEFAULT": 20  // UI「最低份數」欄位預設
}
```

若 `config.json` 不存在或讀取失敗,會用內建預設值。

### UI 使用流程

1. **匯入處方紀錄**:選擇 Excel 檔(包含「處方紀錄」分頁)
2. **申報設定**:年份、月份、健管費最低份數
   - 份數必須是 `PEOPLE_DIVISOR` (預設 4)的倍數,否則不能產生
3. **勾選要產生的文件**
4. **人員個資檔**:選填,會帶入領據的身分證、地址、銀行等
5. **輸出位置**:產出檔案放哪
6. 按「產 生 文 件」

---

## 給開發者

### 開發環境

```bash
# Python 3.13 + tkinter
pip install -r requirements.txt
```

### 直接跑(不打包)

```bash
python app.py
```

`config.json` 放在專案根目錄即可(跟 `app.py` 同層)。

### 打包 exe

```cmd
build.bat
```

會產出 `dist/核銷文件產生器.exe` 與 `dist/config.json`。把這兩個檔一起給使用者。

### 專案結構

```
health-plan-docx-generator/
├── app.py                    GUI 主程式
├── config.py                 設定常數(讀 config.json,fallback 用內建)
├── config.json               ★ 費用/門檻可調整
├── models.py                 Dataclass:AllData, DoctorPrescription, ...
├── reader.py                 讀處方紀錄 Excel → AllData
├── excel_writer.py           產生 Excel 輸出
├── people_db.py              人員個資 Excel 讀寫
├── receipt_reader.py         從舊領據 docx 匯入人員資料
├── generate.py               CLI 入口(保留,目前主要走 app.py)
├── pdf_merge.py              PDF 合併工具
├── templates/
│   ├── clinic.py             核銷總表(處方費/執行費/健管費)
│   ├── clone_fill.py         直接從 Word 模板複製格式填數據
│   ├── doc_utils.py          docx 共用工具
│   ├── executor.py           執行人員文件 + 健管費個別檔
│   └── receipt.py            領據
├── word_templates/           使用者提供的樣板 docx
├── 核銷文件產生器.spec        PyInstaller spec
├── build.bat                 一鍵打包
├── requirements.txt
└── README.md
```

### 架構備忘

- **config.py 是唯一費用來源**。新增費用常數時加到 `config.py` + `config.json` + `_DEFAULTS`,所有模組從 `config` import。
- **`AllData.min_prescriptions`** 由 UI 填入,`read_prescription_report` 存進 data,`_add_health_mgmt_page` 從 `data.min_prescriptions` 讀取。不要再用 module-level 變數傳值。
- **Word 模板** (`word_templates/*.docx`) 是使用者提供的實際格式,`clone_fill` 把第一筆當樣板複製 N 份替換數字。改模板不用改程式碼。

### 除錯

執行時若 UI log 顯示 `設定檔來源: (defaults)` → 代表 `config.json` 沒找到或讀取失敗,請檢查是否跟 exe 同目錄。
