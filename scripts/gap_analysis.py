"""平响排查 server 面分析：全量会话 user->assistant 间隔 + duration_time + failed 签名 + 事故窗口定位
用法:
  python gap_analysis.py --workspace <ws> --agent <cfg_id> --day 2026-09-18 [--sample N] [--gap-threshold 60]
  python gap_analysis.py --check                     # 验证 cs-cli 认证
  python gap_analysis.py ... --output result.json    # 统计结果落盘
输出: 日级/小时级统计、事故窗口(自动聚类连续慢消息)、failed 记录、剔除窗口后的基线对比。
"""
import argparse, json, subprocess, statistics, sys, os, shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from exceptions import categorize_cli_error, ParseError, TimeoutError, NetworkError

# BetterYeah 业务统一北京时间(UTC+8)
CST = timezone(timedelta(hours=8))

# 解析顺序: 环境变量 CS_CLI > PATH 上的 cs-cli（Windows 下 PATHEXT 会命中 cs-cli.cmd）
CS = os.environ.get("CS_CLI") or shutil.which("cs-cli") or "cs-cli"

def parse(raw):
    return json.JSONDecoder().raw_decode(raw)[0]

def run_cli(ws, args):
    try:
        r = subprocess.run([CS, "--workspace", ws] + args, capture_output=True, text=True,
                           encoding="utf-8", timeout=120)
    except subprocess.TimeoutExpired as e:
        raise categorize_cli_error(e, "cs-cli")
    except OSError as e:
        raise categorize_cli_error(e, "cs-cli")
    try: 
        return parse(r.stdout)
    except json.JSONDecodeError as e:
        raise ParseError(f"JSON解析失败: {e}", source="cs-cli")

def conv_list(ws, agent, day):
    convs = {}
    page = 1
    while True:
        d = run_cli(ws, ["conversation", "list", "--agent", agent, "--start", f"{day}T00:00:00",
                         "--end", f"{day}T23:59:59", "--page-size", "100", "--page", str(page)])
        if not d: break
        data = d.get("data") or {}
        for c in data.get("items") or []:
            convs[c["conversation_id"]] = c
        pg = data.get("pagination") or {}
        if page >= pg.get("total_pages", 1): break
        page += 1
    return convs

def fetch(ws, cid):
    d = run_cli(ws, ["conversation", "records", cid, "--page-size", "50"])
    return (cid, d.get("data") or []) if d else None

def ts(s):
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=CST)

def check():
    try:
        r = subprocess.run([CS, "auth", "whoami"], capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        d = parse(r.stdout)
        if d.get("success"):
            print(f"✅ cs-cli 已认证（{CS}）"); sys.exit(0)
        print("❌ cs-cli 未登录或异常"); sys.exit(1)
    except Exception as e:
        print(f"❌ cs-cli 不可用: {e}"); sys.exit(1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace")
    ap.add_argument("--agent")
    ap.add_argument("--day")
    ap.add_argument("--sample", type=int, default=0, help="每小时抽样会话数; 0=全量")
    ap.add_argument("--gap-threshold", type=float, default=60.0)
    ap.add_argument("--check", action="store_true", help="验证 cs-cli 认证")
    ap.add_argument("--output", help="保存统计结果 JSON 文件路径")
    a = ap.parse_args()

    if a.check:
        check()

    if not (a.workspace and a.agent and a.day):
        ap.error("需要 --workspace --agent --day（或 --check）")

    convs = conv_list(a.workspace, a.agent, a.day)
    ids = list(convs)
    if a.sample:
        buckets = defaultdict(list)
        for cid, c in convs.items():
            buckets[(c.get("created_at") or "")[11:13]].append(cid)
        ids = [x for h in sorted(buckets) for x in buckets[h][::max(1, len(buckets[h])//a.sample)][:a.sample]]
    print(f"day={a.day} convs={len(convs)} analyzed={len(ids)}", file=sys.stderr)

    gaps, durs, failed = [], [], []
    # 自适应并发度：会话少时降并发（轻量、规避 SLS/API 限流），多时适度升（上限 10）
    worker_count = min(10, max(2, len(ids) // 50)) if ids else 1
    print(f"并发度={worker_count}（会话数 {len(ids)}）", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=worker_count) as ex:
        for res in ex.map(lambda c: fetch(a.workspace, c), ids):
            if not res: continue
            cid, msgs = res
            rows = sorted([m for m in msgs if m.get("message_time")], key=lambda m: m["message_time"])
            last_user = None
            for m in rows:
                if not m["message_time"].startswith(a.day):
                    last_user = None; continue
                if m["role"] == "user": last_user = m["message_time"]
                elif m["role"] == "assistant":
                    if m.get("record_status") == "failed":
                        failed.append((m["message_time"], cid, m.get("send_results"), m.get("error_detail")))
                    if m.get("duration_time"): durs.append(m["duration_time"])
                    if last_user:
                        try:
                            g = (ts(m["message_time"]) - ts(last_user)).total_seconds()
                            if 0 <= g < 3600: gaps.append((m["message_time"], cid, g))
                        except (ValueError, TypeError) as e:
                            print(f"[WARN] 时间解析失败 conv={cid} assistant_time={m.get('message_time')} user_time={last_user}: {e}", file=sys.stderr)
                        last_user = None
    gaps.sort()
    def q(xs, p): xs = sorted(xs); return xs[min(len(xs)-1, int(p*len(xs)))] if xs else -1
    def st(label, xs):
        print(f"{label}: n={len(xs)} mean={statistics.mean(xs):.1f} med={q(xs,.5):.1f} p90={q(xs,.9):.1f} max={max(xs):.1f}" if xs else f"{label}: none")
    st("ALL user->assistant gap", [g for _, _, g in gaps])
    st("server duration_time", durs)

    slow = [(t, cid, g) for t, cid, g in gaps if g > a.gap_threshold]
    print(f"\nslow(>{a.gap_threshold:.0f}s): {len(slow)}")
    # 聚类连续慢消息 => 事故窗口
    clusters, cur = [], []
    for t, cid, g in slow:
        if cur and (ts(t) - ts(cur[-1][0])).total_seconds() > 1800:
            clusters.append(cur); cur = []
        cur.append((t, cid, g))
    if cur: clusters.append(cur)
    for cl in clusters:
        print(f"  cluster {cl[0][0][:16]}~{cl[-1][0][:16]} n={len(cl)} mean={statistics.mean([g for _,_,g in cl]):.0f}s convs: {sorted(set(c for _,c,_ in cl))}")
    excl = [g for t, _, g in gaps if not any(c[0][0][11:13] <= t[11:13] <= c[-1][0][11:13] for c in clusters)] if clusters else [g for _, _, g in gaps]
    st("\nEXCLUDING incident clusters gap", excl)
    print("\nfailed sends (top15):")
    for f in sorted(failed)[:15]: print(" ", f)

    if a.output:
        result = {
            "day": a.day, "workspace": a.workspace, "agent": a.agent,
            "convs": len(convs), "analyzed": len(ids), "gap_threshold": a.gap_threshold,
            "stats": {
                "gap": {"n": len(gaps), "mean": round(statistics.mean([g for _, _, g in gaps]), 1) if gaps else None,
                        "med": q([g for _, _, g in gaps], .5), "p90": q([g for _, _, g in gaps], .9),
                        "max": round(max([g for _, _, g in gaps]), 1) if gaps else None},
                "duration": {"n": len(durs), "mean": round(statistics.mean(durs), 1) if durs else None,
                             "med": q(durs, .5), "p90": q(durs, .9), "max": round(max(durs), 1) if durs else None},
                "excl_clusters": {"n": len(excl), "mean": round(statistics.mean(excl), 1) if excl else None,
                                  "med": q(excl, .5), "p90": q(excl, .9)},
            },
            "slow_count": len(slow),
            "clusters": [{"start": c[0][0], "end": c[-1][0], "n": len(c),
                          "mean_gap": round(statistics.mean([g for _, _, g in c]), 1),
                          "convs": sorted(set(x for _, x, _ in c))} for c in clusters],
            "failed": [{"time": t, "conversation_id": cid, "send_results": sr, "error_detail": ed}
                       for t, cid, sr, ed in sorted(failed)[:50]],
            "errors": {
                "description": "查询失败或数据解析异常时填充此字段",
                "items": []
            }
        }
        out = Path(a.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✅ 已保存统计结果: {out}")

if __name__ == "__main__":
    main()
