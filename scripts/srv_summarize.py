#!/usr/bin/env python3
"""服务端日志摘要：按时间打印关键行（可过滤关键词），并统计消息模式。

用法: python3 srv_summarize.py --file <json> [--start 12:15] [--end 13:15] [--grep kw1,kw2] [--max 400]
"""
import argparse
import collections
import json
import re
from datetime import datetime


def ts(r):
    if r.get("time"):  # 'YYYY-MM-DD HH:MM:SS' 已北京时间
        try:
            return datetime.strptime(str(r["time"])[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    t = r.get("__time__") or r.get("__time___0") or r.get("ts")
    try:
        return datetime.fromtimestamp(int(t))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--grep")
    ap.add_argument("--max", type=int, default=400)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    rows = json.load(open(args.file, encoding="utf-8"))
    rows = [r for r in rows if isinstance(r, dict)]
    rows.sort(key=lambda r: (str(r.get("__time__")), str(r.get("__time_ns_part__", ""))))
    kws = [k.strip() for k in args.grep.split(",")] if args.grep else None

    def keep(r):
        t = ts(r)
        if t is None:
            return False
        hm = t.strftime("%H:%M:%S")
        if args.start and hm < args.start:
            return False
        if args.end and hm > args.end:
            return False
        if kws:
            msg = str(r.get("message", "")) + str(r.get("content", ""))
            return any(k in msg for k in kws)
        return True

    sel = [r for r in rows if keep(r)]
    print("matched", len(sel), "of", len(rows))
    for r in sel[: args.max]:
        t = ts(r)
        msg = str(r.get("message", r.get("content", ""))).replace("\n", " ")[:260]
        print("[%s] %s %s | %s" % (t.strftime("%H:%M:%S"), r.get("level", ""), r.get("module", ""), msg))

    if args.stats:
        print("\n--- top module.function ---")
        c = collections.Counter((r.get("module"), r.get("function")) for r in rows)
        for k, v in c.most_common(25):
            print(v, "|", k)
        print("\n--- message patterns ---")
        pat = collections.Counter()
        for r in rows:
            m = str(r.get("message", r.get("content", "")))
            m = re.sub(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?", "<ts>", m)
            m = re.sub(r"\b[0-9a-f]{32}\b", "<cid>", m)
            m = re.sub(r"\d+", "N", m)
            pat[m[:120]] += 1
        for k, v in pat.most_common(30):
            print(v, "|", k)


if __name__ == "__main__":
    main()
