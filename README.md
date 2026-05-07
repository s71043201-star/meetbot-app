# 核銷文件產生器 v39（網頁美化版）

HTML 介面 + Python 後端，**真的能產出 Word / PDF / 寄送 Gmail**。
不再使用 pywebview —— 改用本機瀏覽器（Chrome / Edge / Firefox 皆可），更穩定。

---

## 使用方式（需安裝 Python）

> **前提**：電腦先安裝 **Python 3.10 以上**
> 下載：https://www.python.org/downloads/
> ⚠️ 安裝時務必勾選「**Add Python to PATH**」

### 啟動步驟
1. 下載本專案 → 解壓縮到固定位置（例如桌面）
2. 進入 `v39_webview/` 資料夾
3. 雙擊 **`啟動.py`**
   - 第一次會自動 `pip install` 所需套件（1~3 分鐘）
   - 之後就直接開程式
4. 程式會：
   - 啟動本機 server `http://127.0.0.1:5173/`
   - 自動用預設瀏覽器開啟介面
   - 保留 cmd 視窗（**請勿關閉**，關閉等於關掉程式）

### 從命令列啟動（雙擊閃退時用）
```
cd 路徑\v39_webview
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
v39_webview/
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
└── 核銷文件產生器_v39.spec   # PyInstaller 打包設定
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
cd v39_webview
git init
git add .
git commit -m "v39 網頁美化版（瀏覽器 + Python 後端）"
git branch -M main
git remote add origin https://github.com/<你的帳號>/<repo名稱>.git
git push -u origin main
```
