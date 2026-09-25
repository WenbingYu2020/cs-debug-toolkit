#!/usr/bin/env python3
"""列出某 agent 指定日期的全部会话（自动翻页）。

用法: python3 conv_list_all.py --workspace <ws> --agent <config_id> --day 2026-09-25 [--out file.json]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from csapi import data  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--day", required=True)
    ap.add_argument("--page-size", type=int, default=100)
    ap.add_argument("--out")
    args = ap.parse_args()

    out, page = [], 1
    while True:
        d = data(["conversation", "list", "--workspace", args.workspace, "--agent", args.agent,
                  "--start", "%sT00:00:00" % args.day, "--end", "%sT23:59:59" % args.day,
                  "--page", str(page), "--page-size", str(args.page_size)])
        if not d:
            break
        items = d.get("items", d) if isinstance(d, dict) else d
        out.extend(items)
        total = d.get("total") if isinstance(d, dict) else None
        if len(items) < args.page_size:
            break
        page += 1
        if total and len(out) >= int(total):
            break
    print("conversations:", len(out))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
