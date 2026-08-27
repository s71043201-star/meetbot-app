"""設定健康處方管理系統的帳密（寫進 secrets.json）並立刻測試連線。

比手動編輯 JSON 省事，也不會踩到格式錯、存錯位置、沒存到的坑。
既有的 PEOPLE_DB_* 設定會原樣保留，只更新 RX_ACCOUNT / RX_PASSWORD。

用法：
    python scripts/set_rx_credentials.py

密碼輸入時不會顯示在畫面上，只寫進本機的 secrets.json（該檔已列入
.gitignore，不會進 git）。
"""
from __future__ import annotations

import getpass
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import config


def main() -> int:
    path = config._external_secrets_path()
    print(f"設定檔：{path}")

    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"\n現有 secrets.json 格式有問題（{e}）。")
            if input("要覆蓋成全新的檔案嗎？其他設定會遺失 [y/N] ").strip().lower() != "y":
                return 2
            data = {}

    cur = str(data.get("RX_ACCOUNT") or "")
    if cur:
        print(f"目前帳號：{cur}")
    account = input("帳號（直接按 Enter 保留現有）：").strip() or cur
    if not account:
        print("X 帳號不可空白")
        return 2

    password = getpass.getpass("密碼（輸入時不會顯示）：").strip()
    if not password:
        print("X 密碼不可空白")
        return 2

    data["RX_ACCOUNT"] = account
    data["RX_PASSWORD"] = password
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"\n已寫入 {path}")
    print("  欄位：" + "、".join(
        f"{k}{'(已填)' if v else '(空)'}" for k, v in data.items()))

    # 立刻測試 —— config 是 import 時載入的，要重讀才會拿到新值
    print("\n測試連線…")
    import importlib
    importlib.reload(config)
    import backend_api
    importlib.reload(backend_api)
    try:
        print("  " + backend_api.check_connection())
    except backend_api.RxApiError as e:
        print("  X " + str(e))
        print("\n帳密有誤或該帳號無權限。請確認後重跑本工具。")
        return 1

    print("\n可以接著跑對帳了：")
    print('  python scripts/verify_api_vs_excel.py "<你的執行用 Excel>"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
