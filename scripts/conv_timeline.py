#!/usr/bin/env python3
"""单会话消息时间线：拉 conversation records，打印逐条消息与间隔/耗时/失败签名。

用法:
  python3 conv_timeline.py --workspace <ws> --conv <conversation_id> [--out <json>]
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from csapi import data  # noqa: E402


def parse_naive(s):
    if not s:
        return None
    s = s.replace("Z", "").split("+")[0].strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def fetch(ws, conv, page_size=200):
    """records 无 --page，只有 --page-size / --direction(prev|next)；先取最新一页再向更早翻。"""
    out, seen = [], set()
    direction = None
    while True:
        args = ["conversation", "records", conv, "--workspace", ws, "--page-size", str(page_size)]
        if direction:
            args += ["--direction", direction]
        d = data(args)
        if not d:
            break
        items = d if isinstance(d, list) else d.get("items", [])
        fresh = [r for r in items if r.get("record_id") not in seen]
        for r in fresh:
            seen.add(r.get("record_id"))
        out.extend(fresh)
        if len(items) < page_size or not fresh:
            break
        direction = "prev"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--conv", required=True)
    ap.add_argument("--out")
    ap.add_argument("--raw", action="store_true", help="打印原始全字段")
    args = ap.parse_args()

    recs = fetch(args.workspace, args.conv)
    recs.sort(key=lambda r: (r.get("message_time") or "", r.get("created_at") or ""))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(recs, f, ensure_ascii=False, indent=1)

    print("records:", len(recs))
    prev_speaker = None
    prev_time = None
    for r in recs:
        mt = parse_naive(r.get("message_time"))
        ct = parse_naive(r.get("created_at"))
        speaker = "USER" if (r.get("record_status") == "normal" and r.get("duration_time") in (None, 0)
                             and r.get("agent_duration_time") in (None, 0)) else "AGENT"
        ctx = r.get("context") or {}
        text = (ctx.get("text") or "").replace("\n", " ")[:110]
        gap = ""
        if prev_time and mt:
            gap = " gap=%+.0fs" % (mt - prev_time).total_seconds()
        ingest = " ingest=%+.0fs" % (ct - mt).total_seconds() if (ct and mt) else ""
        print("[%s] %s %s d=%s ad=%s st=%s%s%s | %s" % (
            r.get("message_time"), speaker, r.get("record_id", "")[:8],
            r.get("duration_time"), r.get("agent_duration_time"), r.get("record_status"),
            gap, ingest, text))
        if r.get("send_results"):
            print("        send_results:", json.dumps(r["send_results"], ensure_ascii=False)[:300])
        if r.get("error_detail"):
            print("        error_detail:", str(r["error_detail"])[:300])
        if args.raw:
            print("        RAW:", json.dumps(r, ensure_ascii=False)[:600])
        prev_time = mt or prev_time
        prev_speaker = speaker


if __name__ == "__main__":
    main()
