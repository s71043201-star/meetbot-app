"""Gmail 寄送器 — 一鍵啟動 / 安裝

雙擊這個檔案：
  - 第一次：自動安裝所需套件（30 秒 ~ 1 分鐘）
  - 第二次以後：直接啟動程式

也可以從 cmd 執行：
  py 啟動寄送器.py
"""

import importlib.util
import os
import subprocess
import sys


REQUIRED = [
    ("openpyxl", "openpyxl>=3.1"),
]


def _have(mod):
    return importlib.util.find_spec(mod) is not None


def install_missing():
    missing = [pip_name for mod, pip_name in REQUIRED if not _have(mod)]
    if not missing:
        return
    print("=" * 60)
    print(f"首次使用：需要安裝 {len(missing)} 個套件")
    print("=" * 60)
    for pip_name in missing:
        print(f"\n安裝 {pip_name} ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pip_name])
    print("\n=== 安裝完成 ===\n")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)

    try:
        install_missing()
    except subprocess.CalledProcessError as e:
        print(f"\n[安裝失敗] {e}")
        input("\n按 Enter 結束...")
        return

    print("正在啟動 Gmail 寄送器 2.0.2 ...\n")
    import email_sender_server
    email_sender_server.main()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        input("\n按 Enter 結束...")
