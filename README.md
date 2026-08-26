# 核銷文件產生器 v40（網頁美化版）

HTML 介面 + Python 後端，**真的能產出 Word / PDF / 寄送 Gmail**。
不再使用 pywebview —— 改用本機瀏覽器（Chrome / Edge / Firefox 皆可），更穩定。

---

## v40 變更：處方處置費依課程型態分流計價

核銷新規定後，處置費不再一律 400 元/人次，改依執行的課程型態分三種費率
（計數單位仍是「每筆執行紀錄一筆」，只有單價不同）：

| 課程型態 | 單價 | 判別方式 |
|---|---|---|
| 一般實體課程 | 400 元 | 其餘皆歸此類 |
| 處方PLUS2 | 200 元 | 「執行課程」欄含 `PLUS2`（機構課程也在課名前加 PLUS2） |
| 線上微課程 | 100 元 | 「執行課程」欄比對 `ONLINE_COURSE_NAMES` 線上課清單 |

**線上課一定要比對課名，不能只看執行單位** —— 線上課的「執行單位」填的是講師
所屬的實體單位（士林社大、癌症關懷基金會…），從單位完全看不出是線上課。
實測 8,076 筆裡，只看單位會把 3,965 筆線上課誤算成 400 元。

線上課清單與處方儀表板（tpma-statistics）同一份定義：課程管理裡
`delivery_mode != 'offline'` 的課。課名比對前會去掉開頭數字（課務每天會在課名
前加數字）、去空白、轉小寫，與儀表板 `course_slot_stats.online_name_map` 的
正規化規則一致。**課程有新增／下架時要重新同步清單**：

```bash
python scripts/sync_online_courses.py --dry-run   # 先看差異
python scripts/sync_online_courses.py             # 確認後寫入 config.json
```

費率與清單都在 `config.json`，**改這些不用重新打包 exe**。

### 文件輸出的對應調整

- **領據**：pivot 表依實際用到的費率動態長列（只列有人次的費率），欄名改
  「處置費項目」、各列印費率全名；多列時自動回收等量留白，確保領據維持一頁
- **民眾明細**：依費率分頁，每頁表格下方註記該費率的計算式，最後一頁補跨費率
  總額；每頁內依執行日期排序
- **核銷總表**：多費率時按（費率 × 處方類型）逐列，附註列出各費率

---

## 使用方式（需安裝 Python）

> **前提**：電腦先安裝 **Python 3.10 以上**
> 下載：https://www.python.org/downloads/
> ⚠️ 安裝時務必勾選「**Add Python to PATH**」

### 啟動步驟
1. 下載本專案 → 解壓縮到固定位置（例如桌面）
2. 進入 `v40_webview/` 資料夾
3. 雙擊 **`啟動.py`**
   - 第一次會自動 `pip install` 所需套件（1~3 分鐘）
   - 之後就直接開程式
4. 程式會：
   - 啟動本機 server `http://127.0.0.1:5173/`
   - 自動用預設瀏覽器開啟介面
   - 保留 cmd 視窗（**請勿關閉**，關閉等於關掉程式）

### 從命令列啟動（雙擊閃退時用）
```
cd 路徑\v40_webview
py 啟動.py
```
有錯誤訊息會直接印在 cmd，方便排查。

---

## 為什麼需要 Python？

這是一個**網頁前端 + Python 後端**的混合架構：

- **前端**：HTML + React，跑在瀏覽器
- **後端**：Python，負責讀 Excel、產 Word、轉 PDF、寄信
- 兩者透過本機 `http://127.0.0.1:5173/` 連通

所以**必須有 Python 環境**才能跑。
若想做成單檔 `.exe`（不需 Python），執行 `build_webview.bat` 打包。

---

## 結構

```
v40_webview/
├── 啟動.py                  # 一鍵啟動（自動裝套件 + 開瀏覽器）
├── app_server.py            # HTTP server + API（核心入口）
├── reader.py / excel_writer.py / models.py / ...   # 核心邏輯
├── templates/               # 產 Word 邏輯
├── word_templates/          # Word 範本 .docx
├── web_ui/                  # HTML 介面
│   ├── index.html
│   ├── app.jsx              # React 美化版 UI
│   ├── app.css
│   └── email_preview.html
├── requirements.txt
└── 核銷文件產生器_v40.spec   # PyInstaller 打包設定
```

---

## 故障排除

| 問題 | 處理 |
|---|---|
| 雙擊 `啟動.py` 閃退 | 用 cmd 執行 `py 啟動.py` 看錯誤訊息 |
| `ModuleNotFoundError: app_server` | 確認你是從**解壓後的資料夾**執行，不是直接從 zip 預覽執行 |
| 點選檔按鈕沒反應 | 對話框被其他視窗擋住；按 Alt+Tab 切換看看 |
| `docx2pdf` 失敗 | Word→PDF 需要本機安裝 Microsoft Word |
| 瀏覽器沒自動開 | 手動瀏覽 http://127.0.0.1:5173/ |

---

## 推上 GitHub

```bash
cd v40_webview
git init
git add .
git commit -m "v40 網頁美化版（瀏覽器 + Python 後端）"
git branch -M main
git remote add origin https://github.com/<你的帳號>/<repo名稱>.git
git push -u origin main
```
