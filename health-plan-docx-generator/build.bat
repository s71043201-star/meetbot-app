@echo off
REM 健康台灣深耕計畫 核銷文件產生器 — 打包腳本
REM
REM 執行前提:
REM   1. 已安裝 Python 3.13 (含 tkinter)
REM   2. pip install -r requirements.txt
REM
REM 執行結果:
REM   dist\核銷文件產生器.exe      ← 新的執行檔
REM   dist\config.json             ← 設定檔(費用/門檻),與 exe 同目錄

cd /d "%~dp0"

echo [1/3] 安裝/更新相依套件
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo [2/3] PyInstaller 打包
python -m PyInstaller --clean --noconfirm 核銷文件產生器.spec
if errorlevel 1 goto :fail

echo.
echo [3/3] 複製 config.json 到 dist/
copy /Y config.json dist\config.json >nul
if errorlevel 1 goto :fail

echo.
echo ====================================
echo  完成! exe 與 config.json 在 dist\
echo  若要調整費用/門檻,直接編輯 dist\config.json
echo  (不用重新打包)
echo ====================================
exit /b 0

:fail
echo.
echo !!! 打包失敗,請看上面的錯誤訊息
exit /b 1
