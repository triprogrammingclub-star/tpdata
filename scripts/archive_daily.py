#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
archive_daily.py（taipower-bot-02 專用）

每月 1 號觸發，把「上個月及以前」還散落在根目錄的檔案，
歸檔到各資料夾下的「每日」子資料夾（沿用本 repo 現有風格：YYYYMMDD）。

處理資料夾：genary, genload, genloadareaperc, region,
            loadpara_txt, loadpara_json, supply_demand
不處理：    loadareas, fuel_type

檔名格式（兩類）：
  西元12碼：YYYYMMDDHHmm.xxx   例：202605210040.txt
            → 日期資料夾直接取前8碼 YYYYMMDD

  民國11碼：YYYMMDDHHmm.xxx    例：11506211620.json
            → 前5碼是民國年月日（YYY+MM+DD），轉西元：西元年=民國年+1911
            → 日期資料夾為轉換後的 YYYYMMDD

  loadpara_json、supply_demand 兩種格式混雜，依碼數自動判斷（12碼=西元，11碼=民國）。
  其餘資料夾固定西元12碼。

用 Git Trees API 批次移動：一次 commit 搬多個檔，避免大量 API 呼叫。
只搬「已在資料夾根目錄散落」的檔，已在日期子資料夾內的不動。

環境變數：
  GH_TOKEN   GitHub token（Actions 用內建 GITHUB_TOKEN 即可）
  GH_OWNER   repo owner
  GH_REPO    repo 名稱
  GH_BRANCH  分支（預設 main）
"""

import os
import re
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from collections import Counter

# ── 設定 ──
TOKEN  = os.environ.get("GH_TOKEN")
OWNER  = os.environ.get("GH_OWNER")
REPO   = os.environ.get("GH_REPO")
BRANCH = os.environ.get("GH_BRANCH", "main")

# 資料夾在 repo 裡的位置前綴（此 repo 資料夾直接在根目錄，故為空字串）
DATA_PREFIX = ""

FOLDERS = [
    "genary", "genload", "genloadareaperc", "region",
    "loadpara_txt", "loadpara_json", "supply_demand"
]

API = "https://api.github.com"


def gh_request(method, url, data=None):
    if data is not None:
        data = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body}


def check_env():
    missing = [k for k in ["GH_TOKEN", "GH_OWNER", "GH_REPO"] if not os.environ.get(k)]
    if missing:
        print(f"❌ 缺少環境變數：{', '.join(missing)}")
        sys.exit(1)


def current_ymd():
    """現在的西元年月日字串（YYYYMMDD），台灣時間。用於算「上個月」截止點。"""
    tw = datetime.now(timezone(timedelta(hours=8)))
    return tw.strftime("%Y%m%d")


def current_month_first_western():
    """本月1號的西元 YYYYMM01 字串，用於判斷「上個月及以前」的截止。"""
    tw = datetime.now(timezone(timedelta(hours=8)))
    return f"{tw.year:04d}{tw.month:02d}01"


def parse_file_date_to_western(filename):
    """
    從檔名解析出西元日期字串 YYYYMMDD。
    自動判斷民國(11碼)或西元(12碼)開頭。
    無法解析回傳 None。
    """
    m = re.match(r"^(\d{11,12})", filename)
    if not m:
        return None
    digits = m.group(1)

    if len(digits) >= 12:
        # 西元：YYYYMMDDHHmm...
        ymd = digits[:8]
        # 基本合理性檢查
        try:
            datetime.strptime(ymd, "%Y%m%d")
            return ymd
        except ValueError:
            return None
    else:
        # 11碼：民國 YYYMMDDHHmm
        roc_ymd = digits[:7]   # YYY+MM+DD
        try:
            roc_year = int(roc_ymd[:3])
            month    = roc_ymd[3:5]
            day      = roc_ymd[5:7]
            western_year = roc_year + 1911
            ymd = f"{western_year:04d}{month}{day}"
            datetime.strptime(ymd, "%Y%m%d")
            return ymd
        except (ValueError, IndexError):
            return None


def get_branch_head():
    status, ref = gh_request("GET", f"{API}/repos/{OWNER}/{REPO}/git/ref/heads/{BRANCH}")
    if status != 200:
        print(f"❌ 取得分支 ref 失敗：{ref}")
        sys.exit(1)
    commit_sha = ref["object"]["sha"]

    status, commit = gh_request("GET", f"{API}/repos/{OWNER}/{REPO}/git/commits/{commit_sha}")
    if status != 200:
        print(f"❌ 取得 commit 失敗：{commit}")
        sys.exit(1)
    tree_sha = commit["tree"]["sha"]
    return commit_sha, tree_sha


def get_full_tree(tree_sha):
    status, tree = gh_request(
        "GET", f"{API}/repos/{OWNER}/{REPO}/git/trees/{tree_sha}?recursive=1"
    )
    if status != 200:
        print(f"❌ 取得 tree 失敗：{tree}")
        sys.exit(1)
    if tree.get("truncated"):
        print("⚠️ tree 資料被截斷（檔案過多），本次可能無法一次處理完，建議分批多跑幾次")
    return tree["tree"]


def main():
    check_env()
    cutoff = current_month_first_western()   # 本月1號（西元），搬「早於此」的資料
    print(f"[歸檔] 截止日（不含）：{cutoff}（歸檔此日期之前的散落檔案，即上個月及以前）")

    commit_sha, tree_sha = get_branch_head()
    all_items = get_full_tree(tree_sha)

    prefix_parts = DATA_PREFIX.split("/") if DATA_PREFIX else []
    depth = len(prefix_parts) + 2   # prefix... + folder + filename

    moves = []   # (old_path, new_path, blob_sha)
    for item in all_items:
        if item["type"] != "blob":
            continue
        path = item["path"]
        parts = path.split("/")
        if len(parts) != depth:
            continue   # 深度不符：不是「資料夾根目錄下的散檔」，可能已在日期子資料夾

        if prefix_parts and parts[:len(prefix_parts)] != prefix_parts:
            continue

        folder = parts[len(prefix_parts)]
        filename = parts[len(prefix_parts) + 1]
        if folder not in FOLDERS:
            continue

        ymd = parse_file_date_to_western(filename)
        if not ymd:
            continue
        if ymd >= cutoff:
            continue   # 本月及以後不搬

        prefix_path = "/".join(prefix_parts + [folder]) if prefix_parts else folder
        new_path = f"{prefix_path}/{ymd}/{filename}"
        moves.append((path, new_path, item["sha"]))

    if not moves:
        print("[歸檔] 沒有需要歸檔的檔案，結束")
        return

    print(f"[歸檔] 找到 {len(moves)} 個檔案要歸檔")

    stat = Counter()
    for _, new_path, _ in moves:
        p = new_path.split("/")
        # 統計到「資料夾/日期」層級（若有 DATA_PREFIX 會多一層，取後兩層即可）
        stat_key = "/".join(p[-3:-1]) if len(p) >= 3 else "/".join(p[:-1])
        stat[stat_key] += 1
    for k in sorted(stat):
        print(f"  {k}：{stat[k]} 個")

    # 批次搬移（同前一支程式邏輯）
    BATCH_FILES = 400
    base_tree = tree_sha
    parent = commit_sha

    for i in range(0, len(moves), BATCH_FILES):
        batch_moves = moves[i:i + BATCH_FILES]
        changes = []
        for old_path, new_path, blob_sha in batch_moves:
            changes.append({"path": old_path, "mode": "100644", "type": "blob", "sha": None})
            changes.append({"path": new_path, "mode": "100644", "type": "blob", "sha": blob_sha})

        status, new_tree = gh_request("POST", f"{API}/repos/{OWNER}/{REPO}/git/trees", {
            "base_tree": base_tree,
            "tree": changes
        })
        if status not in (200, 201):
            print(f"❌ 建立 tree 失敗（批次 {i//BATCH_FILES + 1}）：{new_tree}")
            sys.exit(1)

        msg = f"歸檔：移動 {len(batch_moves)} 個檔案到日期資料夾（批次 {i//BATCH_FILES + 1}）"
        status, new_commit = gh_request("POST", f"{API}/repos/{OWNER}/{REPO}/git/commits", {
            "message": msg,
            "tree": new_tree["sha"],
            "parents": [parent]
        })
        if status not in (200, 201):
            print(f"❌ 建立 commit 失敗：{new_commit}")
            sys.exit(1)

        status, upd = gh_request("PATCH", f"{API}/repos/{OWNER}/{REPO}/git/refs/heads/{BRANCH}", {
            "sha": new_commit["sha"],
            "force": False
        })
        if status not in (200, 201):
            print(f"❌ 更新分支失敗：{upd}")
            sys.exit(1)

        base_tree = new_tree["sha"]
        parent = new_commit["sha"]
        print(f"  ✅ 批次 {i//BATCH_FILES + 1} 完成，已 commit {len(batch_moves)} 個檔案")

    print(f"[歸檔] 🎉 全部完成，共歸檔 {len(moves)} 個檔案")


if __name__ == "__main__":
    main()
