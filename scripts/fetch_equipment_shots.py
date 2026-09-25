#!/usr/bin/env python3
"""设备桌面截图回放取证：从 handle_upload 帧清单签名下载 PNG。

流程（见 memory: screenshot-replay-access）：
 1) SLS 查 bty-prod-ack-log/customer-servhub-api 全文 'handle_upload and <equipment_id>'（不带引号）
    → message 内 file_url:servhub/equipment/<eqid>/<uuid>_<eqid>_N.png（30s 一帧）
 2) POST https://customer-servhub-api.betteryeah.com/v1/knowledge/oss/sign-url
    body {"source": "<完整 key>"}，header: Authorization Bearer <~/.cs-cli/credentials.json accessToken> + Workspace-Id
 3) 下载 PNG 到 --out-dir

用法:
  python3 fetch_equipment_shots.py --equipment-id <eqid> --workspace <ws> \
      --start "2026-09-25T12:15:00" --end "2026-09-25T13:15:00" \
      [--pick 12:20:00,13:07:00] [--out-dir dir] [--list-only]
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime

from aliyun.log import LogClient, GetLogsRequest  # noqa: E402

SIGN_URL = "https://customer-servhub-api.betteryeah.com/v1/knowledge/oss/sign-url"
CRED = os.path.join(os.path.expanduser("~"), ".cs-cli", "credentials.json")
FRAME_RE = re.compile(r"file_url:(servhub/equipment/[^\s,}'\"\]]+)")


def sls_config():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "channels.json")
    return json.load(open(p, encoding="utf-8"))


def sls_select(cfg, project, logstore, search, where, start, end, limit=2000):
    client = LogClient(cfg["endpoint"], cfg["access_key_id"], cfg["access_key_secret"])
    from_ts = int(datetime.fromisoformat(start).timestamp())
    to_ts = int(datetime.fromisoformat(end).timestamp())
    base = "%s | select * where %s" % (search, where)
    rows, offset = [], 0
    while len(rows) < limit:
        req = GetLogsRequest(project, logstore, from_ts, to_ts, topic="", query="%s limit %d,100" % (base, offset), line=100)
        resp = client.get_logs(req)
        page = []
        for log in resp.get_logs():
            d = {"__time__": log.get_time()}
            d.update(log.get_contents())
            page.append(d)
        if not page:
            break
        rows.extend(page)
        offset += len(page)
    return rows


def list_frames(sls_cfg, equipment_id, start, end, limit=2000):
    rows = sls_select(sls_cfg, "bty-prod-ack-log", "customer-servhub-api",
                      "handle_upload and %s" % equipment_id, "1=1", start, end, limit)
    frames = []
    for r in rows:
        m = str(r.get("message", ""))
        keys = FRAME_RE.findall(m)
        if not keys:
            continue
        ts = r.get("time") or datetime.fromtimestamp(int(r.get("__time__", 0))).strftime("%Y-%m-%d %H:%M:%S")
        for k in keys:
            frames.append({"time": ts, "key": k})
    return frames


def sign(key, token, workspace):
    req = urllib.request.Request(SIGN_URL, data=json.dumps({"source": key}).encode(),
                                headers={"content-type": "application/json",
                                         "Authorization": "Bearer %s" % token,
                                         "Workspace-Id": workspace})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--equipment-id", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--pick", help="逗号分隔的 HH:MM:SS，各取最接近的一帧")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--list-only", action="store_true")
    args = ap.parse_args()

    cfg = sls_config()
    frames = list_frames(cfg, args.equipment_id, args.start, args.end)
    frames.sort(key=lambda f: f["time"])
    print("frames: %d | %s -> %s" % (len(frames), frames[0]["time"] if frames else "-",
                                     frames[-1]["time"] if frames else "-"))
    for f in frames[:5]:
        print("  ", f["time"], f["key"][-60:])

    if args.list_only:
        json.dump(frames, open(os.path.join(args.out_dir, "frames.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        return

    picks = []
    if args.pick:
        for want in args.pick.split(","):
            wt = datetime.strptime(want.strip(), "%H:%M:%S")
            best = min(frames, key=lambda f: abs(
                (datetime.strptime(f["time"][-8:], "%H:%M:%S") - wt).total_seconds()))
            picks.append(best)
    else:
        picks = frames[:1]

    token = json.load(open(CRED, encoding="utf-8"))["accessToken"]
    os.makedirs(args.out_dir, exist_ok=True)
    for f in picks:
        info = sign(f["key"], token, args.workspace)
        d = info.get("data") or {}
        url = d.get("signed_url") or d.get("url") or info.get("url")
        if not url:
            print("sign failed:", json.dumps(info, ensure_ascii=False)[:300])
            continue
        name = "%s_%s.png" % (f["time"].replace(":", "").replace(" ", "_"), f["key"].rsplit("/", 1)[-1][:12])
        path = os.path.join(args.out_dir, name)
        urllib.request.urlretrieve(url, path)
        print("saved:", path, os.path.getsize(path), "bytes", "| frame time", f["time"])


if __name__ == "__main__":
    main()
