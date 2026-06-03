"""
fetch_realtime.py  ─ 每 10 分鐘執行
透過 Cloudflare Worker 抓取台電網頁資料：
  loadpara_json/      loadpara.json  電力供需參數
  loadpara_txt/       loadpara.txt   電力供需參數（txt 版）
  genary/             genary.txt     各機組即時發電量
  genloadareaperc/    genloadareaperc.csv 區域別即時比例

環境變數：WORKER_URL、WORKER_TOKEN（建議設定）
"""

import logging
import os
import re
import sys
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

WORKER_URL = os.environ.get("WORKER_URL", "").rstrip("/")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")

REPO_DIR = Path(__file__).resolve().parents[1]
DIRS = {
    "json": REPO_DIR / "loadpara_json",
    "txt": REPO_DIR / "loadpara_txt",
    "genary": REPO_DIR / "genary",
    "areaperc": REPO_DIR / "genloadareaperc",
}

TARGETS = [
    {"key": "json", "ext": "json"},
    {"key": "txt", "ext": "txt"},
    {"key": "genary", "ext": "txt"},
    {"key": "areaperc", "ext": "csv"},
]


def parse_publish_time(text: str) -> str | None:
    # 民國年格式：115.04.15(三)16:40
    m = re.search(r"(\d{3})\.(\d{2})\.(\d{2})[^\d]*(\d{2}):(\d{2})", text)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}{m.group(5)}"

    # 西元年格式：2026-04-15 17:30 或 2026.04.15 17:30
    m = re.search(r"(\d{4})[.\-](\d{2})[.\-](\d{2})\s+(\d{2}):(\d{2})", text)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}{m.group(5)}"

    return None


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

    any_ok = False
    for target in TARGETS:
        raw = fetch(target["key"])
        if raw is None:
            log.error("%s 失敗，跳過", target["key"])
            continue

        ts = parse_publish_time(raw)
        if ts is None:
            log.error("%s 找不到 publish_time，略過，不存檔", target["key"])
            continue

        out = DIRS[target["key"]] / f"{ts}.{target['ext']}"
        if out.exists() and out.read_text(encoding="utf-8") == raw:
            log.info("內容未變，跳過：%s", out.name)
        else:
            out.write_text(raw, encoding="utf-8", newline="")
            log.info("已儲存：%s", out)
        any_ok = True
        time.sleep(1)

    return any_ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
