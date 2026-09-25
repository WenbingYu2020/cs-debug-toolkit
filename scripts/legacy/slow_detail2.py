import json, os, subprocess, statistics, datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

CS = os.environ.get("CS_CLI") or r"%APPDATA%\npm\cs-cli.cmd"  # 按需改成本机 cs-cli 路径
WS = "0123456789abcdef0123456789abcdef"
convs = json.load(open("convs-918-all.json", encoding="utf-8"))
ids = [c["conversation_id"] for c in convs]

def fetch(cid):
    r = subprocess.run([CS, "--workspace", WS, "conversation", "records", cid, "--page-size", "50"],
                       capture_output=True, text=True, encoding="utf-8")
    try:
        msgs = json.JSONDecoder().raw_decode(r.stdout)[0].get("data") or []
    except Exception:
        return None
    return cid, msgs

cache = []
per_hour = defaultdict(list)      # 9/18 user->assistant gaps
welcome_slow = []
failed_msgs = []
dur918 = []
with ThreadPoolExecutor(max_workers=10) as ex:
    for res in ex.map(fetch, ids):
        if not res:
            continue
        cid, msgs = res
        cache.append((cid, msgs))
        rows = sorted([m for m in msgs if m.get("message_time")], key=lambda m: m["message_time"])
        last_user = None
        for m in rows:
            if not m["message_time"].startswith("2026-09-18"):
                if m["role"] == "user": last_user = None
                continue
            ts = datetime.datetime.fromisoformat(m["message_time"])
            if m["role"] == "user":
                last_user = ts
            elif m["role"] == "assistant":
                if m.get("duration_time"):
                    dur918.append(m["duration_time"])
                if m.get("record_status") == "failed":
                    failed_msgs.append((m["message_time"], cid[:8], m.get("duration_time"), ((m.get("context") or {}).get("text") or "")[:40]))
                if last_user:
                    g = (ts - last_user).total_seconds()
                    if 0 <= g < 3600:
                        per_hour[m["message_time"][11:13]].append(g)
                        if g > 120:
                            tag = "WELCOME" if m.get("message_tag") == "welcome" else "reply"
                            welcome_slow.append((m["message_time"], tag, round(g), cid[:8]))
                last_user = None

json.dump([(cid, [ {k: m.get(k) for k in ("role","message_time","duration_time","record_status","message_tag","send_results","error_detail")} for m in msgs]) for cid, msgs in cache],
          open("conv-msg-cache-918.json", "w", encoding="utf-8"), ensure_ascii=False)

print("=== 9/18-only hourly gap stats ===")
allg = []
for h in sorted(per_hour):
    xs = per_hour[h]; allg.extend(xs)
    print(h, f"n={len(xs):>3} mean={statistics.mean(xs):5.1f} med={statistics.median(xs):5.1f} max={max(xs):6.1f}")
print("ALL day918: n=%d mean=%.1f med=%.1f p90=%.1f" % (len(allg), statistics.mean(allg), statistics.median(allg), sorted(allg)[int(0.9*len(allg))]))
print("\n=== gaps >120s on 9/18 ===")
for w in sorted(welcome_slow): print(w)
print("\n=== failed sends on 9/18 ===")
for f in sorted(failed_msgs): print(f)
print("\nduration_time on 9/18 (assistant msgs): n=%d mean=%.1f med=%.1f p90=%.1f" % (len(dur918), statistics.mean(dur918), statistics.median(dur918), sorted(dur918)[int(0.9*len(dur918))]))
