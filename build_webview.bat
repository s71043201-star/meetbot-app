@echo off
chcp 65001 >nul
echo ============================================
echo   核銷文件產生器 v40 (webview) 打包
echo ============================================
echo.

echo [1/3] 安裝/更新套件…
pip install -r requirements.txt
if errorlevel 1 goto error

echo.
echo [2/3] 清理舊 build…
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [3/3] PyInstaller 打包…
pyinstaller 核銷文件產生器_v40.spec --clean --noconfirm
if errorlevel 1 goto error

echo.
echo ============================================
echo   ✓ 完成！exe 在 dist\ 資料夾
echo ============================================
pause
exit /b 0

:error
echo.
echo ✕ 打包失敗！
pause
exit /b 1
