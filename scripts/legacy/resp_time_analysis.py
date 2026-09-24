import json, subprocess, statistics, datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

CS = r"C:\Users\13328\AppData\Roaming\npm\cs-cli.cmd"

WS = "93edd013139742409019a062d80aa52d"
AGENT = "e1b19a826e4b4c5f951b4b43b2ff54b5"

def parse(raw):
    d, _ = json.JSONDecoder().raw_decode(raw)
    return d

def conv_list(day):
    convs = {}
    for page in (1, 2, 3, 4, 5):
        r = subprocess.run(
            [CS, "--workspace", WS, "conversation", "list", "--agent", AGENT,
             "--start", f"{day}T00:00:00", "--end", f"{day}T23:59:59",
             "--page-size", "100", "--page", str(page)],
            capture_output=True, text=True, encoding="utf-8")
        try:
            d = parse(r.stdout)
        except Exception:
            break
        items = (d.get("data") or {}).get("items") or []
        for c in items:
            convs[c["conversation_id"]] = c
        pg = (d.get("data") or {}).get("pagination") or {}
        if page >= pg.get("total_pages", 1):
            break
    return convs

def sample_per_hour(convs, n=5):
    buckets = defaultdict(list)
    for cid, c in convs.items():
        t = c.get("created_at") or c.get("updated_at")
        buckets[t[11:13]].append(cid)
    out = []
    for h in sorted(buckets):
        ids = buckets[h]
        step = max(1, len(ids) // n)
        out.extend(ids[::step][:n])
    return out

def fetch(cid):
    r = subprocess.run(
        [CS, "--workspace", WS, "conversation", "records", cid, "--page-size", "50"],
        capture_output=True, text=True, encoding="utf-8")
    try:
        msgs = parse(r.stdout).get("data") or []
    except Exception:
        return None
    rows = []
    for m in msgs:
        rows.append({
            "role": m.get("role"),
            "mt": m.get("message_time"),
            "dur": m.get("duration_time"),
            "status": m.get("record_status"),
            "tag": m.get("message_tag"),
        })
    return rows

def analyze(rows):
    """server durations + user->assistant message_time gaps"""
    durs, gaps = [], []
    rows = sorted([r for r in rows if r["mt"]], key=lambda r: r["mt"])
    last_user = None
    for r in rows:
        ts = datetime.datetime.fromisoformat(r["mt"])
        if r["role"] == "user":
            last_user = ts
        elif r["role"] == "assistant":
            if r["tag"] == "welcome" or r["status"] != "success":
                pass
            elif r["dur"] and r["dur"] > 0:
                durs.append(r["dur"])
            if last_user is not None:
                g = (ts - last_user).total_seconds()
                if 0 <= g < 600:
                    gaps.append(g)
                last_user = None
    return durs, gaps

for day in ("2026-09-17", "2026-09-18"):
    convs = conv_list(day)
    ids = sample_per_hour(convs, n=5)
    print(f"\n### {day}: total convs={len(convs)}, sampled={len(ids)}")
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(fetch, ids))
    all_durs, all_gaps = [], []
    hourly = defaultdict(lambda: ([], []))
    for cid, rows in zip(ids, results):
        if not rows:
            continue
        durs, gaps = analyze(rows)
        all_durs.extend(durs); all_gaps.extend(gaps)
        h = None
        for r in rows:
            if r["role"] == "assistant" and r["mt"]:
                h = r["mt"][11:13]; break
        if h:
            hourly[h][0].extend(durs); hourly[h][1].extend(gaps)
    def stat(name, xs):
        if not xs:
            print(f"{name}: (none)")
            return
        xs = sorted(xs)
        p = lambda q: xs[min(len(xs)-1, int(q*len(xs)))]
        print(f"{name}: n={len(xs)} mean={statistics.mean(xs):.1f}s med={p(0.5):.1f}s p90={p(0.9):.1f}s max={max(xs):.1f}s")
    stat("server duration_time", all_durs)
    stat("user->assistant gap ", all_gaps)
    print("hourly mean gap:", {h: (round(statistics.mean(g),1) if g else None, len(g)) for h,(d_,g) in sorted(hourly.items())})
