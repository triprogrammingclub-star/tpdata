"""
fetch_daily.py  ─ 每日執行（建議台灣時間 01:00~06:00）
透過 Cloudflare Worker 抓取：
  fuel_type/  loadfueltype_1.csv  前一天能源別發電量
  loadareas/  loadareas_1.csv     前一天區域別用電量

檔名：西元年月日，例如 20260414（前一天台灣日期）
環境變數：WORKER_URL、WORKER_TOKEN（建議設定）
"""

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

WORKER_URL = os.environ.get("WORKER_URL", "").rstrip("/")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")

REPO_DIR = Path(__file__).resolve().parents[1]
DIRS = {
    "fueltype": REPO_DIR / "fuel_type",
    "areas": REPO_DIR / "loadareas",
}

TARGETS = [
    {"key": "fueltype", "ext": "csv"},
    {"key": "areas", "ext": "csv"},
]


def yesterday_tw() -> str:
    tw = timezone(timedelta(hours=8))
    return (datetime.now(tw) - timedelta(days=1)).strftime("%Y%m%d")


def fetch(file_key: str) -> str | None:
    if not WORKER_URL:
        log.error("未設定 WORKER_URL")
        sys.exit(1)

    params = {"file": file_key}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; taipower-archive/1.0)"}
    if WORKER_TOKEN:
        headers["Authorization"] = f"Bearer {WORKER_TOKEN}"
        params["token"] = WORKER_TOKEN  # 兼容舊版 Worker 寫法

    for attempt in range(1, 4):
        try:
            log.info("[%s/3] 取得 %s", attempt, file_key)
            resp = requests.get(WORKER_URL, params=params, headers=headers, timeout=20)
            resp.raise_for_status()
            log.info("成功 %s bytes", len(resp.content))
            return resp.text
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            log.warning("HTTP %s", status)
        except requests.RequestException as exc:
            log.warning("連線錯誤：%s", exc)
        if attempt < 3:
            time.sleep(5 * attempt)
    return None


def run() -> bool:
    for d in DIRS.values():
        d.mkdir(parents=True, exist_ok=True)

    date_str = yesterday_tw()
    log.info("前一天台灣日期：%s", date_str)

    any_ok = False
    for target in TARGETS:
        raw = fetch(target["key"])
        if raw is None:
            log.error("%s 失敗，跳過", target["key"])
            continue

        out = DIRS[target["key"]] / f"{date_str}.{target['ext']}"
        if out.exists() and out.read_text(encoding="utf-8") == raw:
            log.info("已存在且內容相同，跳過：%s", out.name)
        else:
            out.write_text(raw, encoding="utf-8", newline="")
            log.info("已儲存：%s", out)
        any_ok = True
        time.sleep(1)

    return any_ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
