"""同步「線上(視訊)課清單」到 config.json

線上課的處置費是 100 元/筆(一般實體課 400 元),但這些課的「執行單位」填的是
講師所屬的實體單位(士林社區大學、癌症關懷基金會…),從單位認不出來 —— 只有
課名認得出來。所以 config.json 要維護一份線上課名清單。

課清單的權威來源是處方儀表板(tpma-statistics)用的那份:課程管理裡
delivery_mode != 'offline' 的課,由 n8n 同步進 Supabase 的
prescription_data.course_slot_stats.online_courses。

課程有新增/下架時跑這支就會更新 config.json。

用法:
    python scripts/sync_online_courses.py            # 同步並寫入
    python scripts/sync_online_courses.py --dry-run  # 只看差異不寫入

Supabase 連線設定直接從儀表板專案的 index.html 讀,不在本專案另存一份金鑰。
儀表板專案路徑可用 --dashboard 指定,預設找 %USERPROFILE%\\OneDrive\\code\\tpma-statistics。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
CONFIG_PATH = PROJECT / "config.json"

DEFAULT_DASHBOARD = Path(
    os.environ.get("USERPROFILE", "")) / "OneDrive" / "code" / "tpma-statistics"


def read_supabase_creds(dashboard_dir: Path) -> tuple[str, str]:
    """從儀表板專案的 index.html 取 Supabase URL / anon key。"""
    index = dashboard_dir / "index.html"
    if not index.is_file():
        raise SystemExit(f"找不到儀表板專案的 index.html: {index}\n"
                         f"用 --dashboard 指定正確路徑。")
    text = index.read_text(encoding="utf-8", errors="ignore")
    m_url = re.search(r"SUPABASE_URL\s*=\s*'([^']+)'", text)
    m_key = re.search(r"SUPABASE_ANON_KEY\s*=\s*'([^']+)'", text)
    if not m_url or not m_key:
        raise SystemExit(f"在 {index} 找不到 SUPABASE_URL / SUPABASE_ANON_KEY")
    return m_url.group(1).strip(), m_key.group(1).strip()


def fetch_online_courses(base_url: str, key: str) -> list[dict]:
    url = (f"{base_url.rstrip('/')}/rest/v1/prescription_data"
           f"?id=eq.main&select=course_slot_stats")
    req = urllib.request.Request(url, headers={
        "apikey": key,
        "Authorization": f"Bearer {key}",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data:
        raise SystemExit("Supabase 沒有回傳 prescription_data(id=main)")
    stats = data[0].get("course_slot_stats") or {}
    courses = stats.get("online_courses")
    if courses is None:
        raise SystemExit(
            "course_slot_stats 沒有 online_courses 欄位 —— "
            "n8n 可能還沒同步過線上課(需重啟 workflow 再同步一次)。")
    return courses


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", type=Path, default=DEFAULT_DASHBOARD,
                    help="tpma-statistics 專案路徑")
    ap.add_argument("--dry-run", action="store_true", help="只顯示差異,不寫入")
    args = ap.parse_args()

    base_url, key = read_supabase_creds(args.dashboard)
    courses = fetch_online_courses(base_url, key)
    names = sorted(str(c.get("name") or "").strip()
                   for c in courses if c.get("name"))

    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    old = list(cfg.get("ONLINE_COURSE_NAMES") or [])

    added = [n for n in names if n not in old]
    removed = [n for n in old if n not in names]

    print(f"儀表板線上課: {len(names)} 門 (本地 config: {len(old)} 門)")
    if added:
        print("\n新增:")
        for n in added:
            print("  +", n)
    if removed:
        print("\n已下架 / 改名:")
        for n in removed:
            print("  -", n)
    if not added and not removed:
        print("\n清單一致,不需更新。")
        return 0

    if args.dry_run:
        print("\n(--dry-run,未寫入)")
        return 0

    cfg["ONLINE_COURSE_NAMES"] = names
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n已更新 {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
