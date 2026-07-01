#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
archive_monthly.py

每月 1 號把「上個月及以前」的檔案，歸檔到各資料夾下的月份子資料夾。
月份子資料夾用民國年月（前5碼），例如 genary/11504/。

處理資料夾：data/genary, data/loadpara_json, data/loadpara_txt, data/loadareas
不處理：data/loadfueltype

（若你的 repo 結構改變，資料夾不在 data/ 底下，改 DATA_PREFIX 變數即可）

檔名格式：
  genary/loadpara_json/loadpara_txt: 11504152300.xxx（民國3+月2+日2+時2+分2 = 11碼）
  loadareas:                          1150414.csv     （民國3+月2+日2 = 7碼）
  兩者年月都取「前5碼」= 民國年月（如 11504）

用 Git Trees API 批次移動：一次 commit 搬多個檔，避免大量 API 呼叫。
只搬「已在根目錄散落」的檔，已在月份子資料夾內的不動。

環境變數：
  GH_TOKEN   GitHub PAT（需 repo 權限）
  GH_OWNER   repo owner
  GH_REPO    repo 名稱
  GH_BRANCH  分支（預設 main）
"""

import os
import re
import sys
import base64
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# ── 設定 ──
TOKEN  = os.environ.get("GH_TOKEN")
OWNER  = os.environ.get("GH_OWNER")
REPO   = os.environ.get("GH_REPO")
BRANCH = os.environ.get("GH_BRANCH", "main")

# 資料夾在 repo 裡的位置前綴（例如 data/genary/... 就填 "data"；若資料夾就在根目錄則填 ""）
DATA_PREFIX = "data"

FOLDERS = ["genary", "loadpara_json", "loadpara_txt", "loadareas"]

API = "https://api.github.com"


def gh_request(method, url, data=None):
    """呼叫 GitHub API，回傳 (status, json)。"""
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


def current_roc_ym():
    """現在的民國年月（前5碼字串），台灣時間。例如 2026-07 → '11507'。"""
    tw = datetime.now(timezone(timedelta(hours=8)))
    roc_year = tw.year - 1911
    return f"{roc_year:03d}{tw.month:02d}"


def parse_file_roc_ym(filename):
    """
    從檔名取民國年月（前5碼）。
    只接受檔名開頭是數字的，取前5碼。
    11504152300.txt → '11504'
    1150414.csv     → '11504'
    無法解析回傳 None。
    """
    m = re.match(r"^(\d{5})\d*", filename)
    if not m:
        return None
    return m.group(1)


def get_branch_head():
    """取得分支最新 commit SHA 與其 tree SHA。"""
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
    """遞迴取得整棵樹的所有 blob 路徑。"""
    status, tree = gh_request(
        "GET", f"{API}/repos/{OWNER}/{REPO}/git/trees/{tree_sha}?recursive=1"
    )
    if status != 200:
        print(f"❌ 取得 tree 失敗：{tree}")
        sys.exit(1)
    if tree.get("truncated"):
        print("⚠️ tree 資料被截斷（檔案過多），本次可能無法一次處理完，建議分批")
    return tree["tree"]


def main():
    check_env()
    cur_ym = current_roc_ym()
    print(f"[歸檔] 當前民國年月：{cur_ym}（此月及以後的檔案保留在根目錄，不歸檔）")

    commit_sha, tree_sha = get_branch_head()
    all_items = get_full_tree(tree_sha)

    # 找出需要搬移的檔案
    # 條件：路徑正好是 [DATA_PREFIX/]<folder>/<filename>（在資料夾根目錄，非子資料夾內）
    #       且檔名年月 < 當前年月
    moves = []   # (old_path, new_path, blob_sha)
    prefix_parts = DATA_PREFIX.split("/") if DATA_PREFIX else []
    depth = len(prefix_parts) + 2   # prefix... + folder + filename

    for item in all_items:
        if item["type"] != "blob":
            continue
        path = item["path"]
        parts = path.split("/")
        if len(parts) != depth:
            continue   # 深度不符（不是 folder/file 這層，可能已在子資料夾或路徑不符）

        if prefix_parts and parts[:len(prefix_parts)] != prefix_parts:
            continue   # 前綴不符

        folder = parts[len(prefix_parts)]
        filename = parts[len(prefix_parts) + 1]
        if folder not in FOLDERS:
            continue

        ym = parse_file_roc_ym(filename)
        if not ym:
            continue
        # 只搬「早於當前月」的
        if ym >= cur_ym:
            continue

        prefix_path = "/".join(prefix_parts + [folder])
        new_path = f"{prefix_path}/{ym}/{filename}"
        moves.append((path, new_path, item["sha"]))

    if not moves:
        print("[歸檔] 沒有需要歸檔的檔案，結束")
        return

    print(f"[歸檔] 找到 {len(moves)} 個檔案要歸檔")

    # 統計各月份數量
    from collections import Counter
    stat = Counter()
    for _, new_path, _ in moves:
        # new_path = folder/ym/filename
        p = new_path.split("/")
        stat[f"{p[0]}/{p[1]}"] += 1
    for k in sorted(stat):
        print(f"  {k}：{stat[k]} 個")

    # 建立新 tree：把舊路徑刪除（設 sha=None）、新路徑指向同一個 blob sha
    # GitHub Git Trees：同一個 base_tree 上，舊路徑用 sha=None 移除，新路徑加入
    tree_changes = []
    for old_path, new_path, blob_sha in moves:
        # 移除舊路徑
        tree_changes.append({
            "path": old_path,
            "mode": "100644",
            "type": "blob",
            "sha": None
        })
        # 新增新路徑（指向同一 blob，不需重新上傳內容）
        tree_changes.append({
            "path": new_path,
            "mode": "100644",
            "type": "blob",
            "sha": blob_sha
        })

    # GitHub 對單次 tree 大小有限制，分批處理（每批 400 個檔案 = 800 個 change）
    BATCH_FILES = 400
    base_tree = tree_sha
    parent = commit_sha

    for i in range(0, len(moves), BATCH_FILES):
        batch_moves = moves[i:i + BATCH_FILES]
        changes = []
        for old_path, new_path, blob_sha in batch_moves:
            changes.append({"path": old_path, "mode": "100644", "type": "blob", "sha": None})
            changes.append({"path": new_path, "mode": "100644", "type": "blob", "sha": blob_sha})

        # 建新 tree
        status, new_tree = gh_request("POST", f"{API}/repos/{OWNER}/{REPO}/git/trees", {
            "base_tree": base_tree,
            "tree": changes
        })
        if status not in (200, 201):
            print(f"❌ 建立 tree 失敗（批次 {i//BATCH_FILES + 1}）：{new_tree}")
            sys.exit(1)

        # 建 commit
        msg = f"歸檔：移動 {len(batch_moves)} 個檔案到月份資料夾（批次 {i//BATCH_FILES + 1}）"
        status, new_commit = gh_request("POST", f"{API}/repos/{OWNER}/{REPO}/git/commits", {
            "message": msg,
            "tree": new_tree["sha"],
            "parents": [parent]
        })
        if status not in (200, 201):
            print(f"❌ 建立 commit 失敗：{new_commit}")
            sys.exit(1)

        # 更新分支指標
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
