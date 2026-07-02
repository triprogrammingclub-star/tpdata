"""
fetch_opendata.py  ─ 每 10 分鐘執行
直接抓台電 OpenData（不繞 Cloudflare Worker）：
  supply_demand/ 電力供需
  genload/       機組發電
  region/        區域別發電用電

找不到資料時間 → 用系統時間存檔，並記錄警告 log。
"""

import csv
import io
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

URL_SUPPLY = "https://service.taipower.com.tw/data/opendata/apply/file/d006020/001.json"
URL_GENLOAD = "https://service.taipower.com.tw/data/opendata/apply/file/d006001/001.json"
URL_REGION = "https://service.taipower.com.tw/data/opendata/apply/file/d006019/001.csv"

REPO_DIR = Path(__file__).resolve().parents[1]
DIRS = {
    "supply": REPO_DIR / "supply_demand",
    "genload": REPO_DIR / "genload",
    "region": REPO_DIR / "region",
}


def now_tw_str() -> str:
    tw = timezone(timedelta(hours=8))
    return datetime.now(tw).strftime("%Y%m%d%H%M")


def fetch(url: str) -> bytes | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; taipower-archive/1.0)",
        "Accept": "application/json,text/csv,text/plain,*/*",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as exc:
        log.error("下載失敗 %s：%s", url, exc)
        return None


def save(dest_dir: Path, filename: str, content: str) -> bool:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / filename
    if out.exists() and out.read_text(encoding="utf-8") == content:
        log.info("內容未變，跳過：%s", filename)
        return False
    out.write_text(content, encoding="utf-8", newline="")
    log.info("已儲存：%s", out)
    return True


def job_supply() -> None:
    log.info("--- 電力供需（OpenData）---")
    raw = fetch(URL_SUPPLY)
    if raw is None:
        return
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        log.error("JSON 解析失敗：%s", exc)
        return

    ts = None
    for rec in data.get("records", []):
        pt = rec.get("publish_time", "")
        digits = re.sub(r"\D", "", pt)
        if len(digits) >= 10:
            ts = digits[:12]
            break

    if ts is None:
        ts = now_tw_str()
        log.warning("supply_demand 找不到 publish_time，用系統時間：%s", ts)

    content = json.dumps(data, ensure_ascii=False, indent=2)
    save(DIRS["supply"], f"{ts}.json", content)


def job_genload() -> None:
    log.info("--- 機組發電（OpenData）---")
    raw = fetch(URL_GENLOAD)
    if raw is None:
        return
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        log.error("JSON 解析失敗：%s", exc)
        return

    raw_time = data.get("DateTime", "")
    digits = re.sub(r"\D", "", raw_time)
    ts = digits[:12] if len(digits) >= 12 else None

    if ts is None:
        ts = now_tw_str()
        log.warning("genload 找不到 DateTime，用系統時間：%s", ts)

    content = json.dumps(data, ensure_ascii=False, indent=2)
    save(DIRS["genload"], f"{ts}.json", content)


def job_region() -> None:
    log.info("--- 區域別發電用電（OpenData）---")
    raw = fetch(URL_REGION)
    if raw is None:
        return
    text = raw.decode("utf-8-sig").strip()

    ts = None
    reader = csv.reader(io.StringIO(text))
    next(reader, None)
    for row in reader:
        if not row:
            continue
        digits = re.sub(r"\D", "", row[0])
        if len(digits) >= 12:
            ts = digits[:12]
            break

    if ts is None:
        ts = now_tw_str()
        log.warning("region 找不到時間，用系統時間：%s", ts)

    save(DIRS["region"], f"{ts}.csv", text)


def run() -> None:
    job_supply()
    job_genload()
    job_region()


if __name__ == "__main__":
    run()
