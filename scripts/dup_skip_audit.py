#!/usr/bin/env python3
"""去重拦截审计：对给定会话列表，找出被"服务端检测重复消息"拦截的回复，判定是否造成漏答。

判定逻辑：
  取被拦截记录（record_status=failed 且 send_results 含"重复消息"）的 reply_user_record_id；
  若该用户消息在会话中没有任何 record_status=success 的 assistant 回复指向它 → 漏答（harmful）；
  否则为无害重跑（去重生效）。

用法:
  python3 dup_skip_audit.py --workspace <ws> --convs-file <ids.txt> [--out audit.json]
  python3 dup_skip_audit.py --workspace <ws> --conv <id> [--conv <id> ...]
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conv_timeline import fetch, parse_naive  # noqa: E402

DUP_KEY = "重复消息"


def audit_conv(ws, conv):
    recs = fetch(ws, conv)
    recs.sort(key=lambda r: (r.get("message_time") or "", r.get("created_at") or ""))
    by_id = {r.get("record_id"): r for r in recs}
    blocked = [r for r in recs if DUP_KEY in str(r.get("send_results") or "")]
    answered = {r.get("reply_user_record_id") for r in recs
                if r.get("record_status") == "success" and r.get("role") == "assistant"}
    rows = []
    for b in blocked:
        target = b.get("reply_user_record_id")
        by_id_t = by_id.get(target) or {}
        t_user = parse_naive(by_id_t.get("message_time")) or parse_naive(b.get("message_time"))
        t_block = parse_naive(b.get("message_time"))
        # 客户消息之后（含同秒）的第一条"已成功发出"的 AI 回复
        ans = [r for r in recs if r.get("record_status") == "success" and r.get("role") == "assistant"
               and (parse_naive(r.get("message_time")) or datetime.min) >= (t_user or datetime.min)]
        t_ans = parse_naive(ans[0].get("message_time")) if ans else None
        # 用户在被拦截消息之后自己又发的消息数（这些消息可能会被再次触发）
        user_after = [r for r in recs if r.get("role") == "user"
                      and (parse_naive(r.get("message_time")) or datetime.min) > (t_user or datetime.min)]
        wait = int((t_ans - t_user).total_seconds()) if (t_ans and t_user) else None
        rows.append({
            "blocked_record_id": b.get("record_id"),
            "blocked_at": b.get("message_time"),
            "reply_target_record_id": target,
            "reply_target_text": by_id_t.get("context", {}).get("text"),
            "reply_target_time": by_id_t.get("message_time"),
            "first_success_reply_at": t_ans.strftime("%Y-%m-%d %H:%M:%S") if t_ans else None,
            "customer_wait_s": wait,
            "user_msgs_after": len(user_after),
            "verdict": ("客户已及时收到回复(去重生效)" if (wait is not None and wait <= 60) else "客户等待>60s(需复核)"),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--conv", action="append", default=[])
    ap.add_argument("--convs-file")
    ap.add_argument("--out")
    args = ap.parse_args()

    convs = list(args.conv)
    if args.convs_file:
        convs += [l.strip() for l in open(args.convs_file, encoding="utf-8") if l.strip()]

    result = {}
    for c in convs:
        try:
            result[c] = audit_conv(args.workspace, c)
        except Exception as e:  # noqa: BLE001
            result[c] = [{"error": str(e)}]

    n_bad = sum(1 for v in result.values() for r in v if r.get("verdict") != "客户已及时收到回复(去重生效)")
    print("conversations audited: %d | 需复核事件(客户等待>60s): %d" % (len(result), n_bad))
    for c, rows in result.items():
        for r in rows:
            print("%s | 拦截@%s | %s | 客户等待=%ss | 被拦截回复目标='%s'@%s | 首条成功回复=%s | 其后用户消息数=%s" % (
                c, r.get("blocked_at"), r.get("verdict"), r.get("customer_wait_s"),
                (r.get("reply_target_text") or "")[:30], r.get("reply_target_time"),
                r.get("first_success_reply_at"), r.get("user_msgs_after")))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
