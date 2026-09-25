#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cross_analysis.py — 多方日志交叉分析证据包生成器（功能区核心）

四个数据源:
  1. 服务端日志   server_log_query.py → SLS bty-prod-ack-log / customer-servhub-api
  2. RPA 端日志   rpa_log_query.py    → SLS customer-servhub-log / project-<channel>-rpa-*
  3. ops 运维日志 ops_log_query.py    → 本地 cs-cli ops-record（运维操作记录）
  4. 主机/IP 侧   --host-bundle        → 主机本地 Windows 事件日志 / 客户端日志
                  --host-events-*      → 目标设备 电源/重启/崩溃 事件专项抓取
                  （collect_rpa_logs.ps1 产出的 zip / ECD 远程拉起文本 / host_events_query.py 重建）
                  ※ ④ 的 SLS 面（equipment→hostname/出口 IP/desktop + robot-health-report
                    心跳时间线）已含在源②的查询里；本参数补的是"主机本地面"，
                    用于把定界从「冻结/崩溃/睡眠/网络」四选一推进到进程级实锤。

本脚本按同一锚点（conversation_id / trace_id / request_id / dispatch_id / 关键词）
+ 同一时间窗口拉取多方日志，做对齐与交叉关联，输出证据包到 temp/，
供 LLM / 人工完成最终的"交叉论证 → 问题结论"。

示例:
  python3 cross_analysis.py --conversation-id 0123456789abcdef0123456789abcdef \
      --channel douyin --start 2026-09-18T10:00:00 --end 2026-09-18T11:00:00

  python3 cross_analysis.py --query "转人工" --level ERROR \
      --start 2026-09-18T00:00:00 --end 2026-09-18T23:59:59

  # 带主机侧证据（第④源）: 事故主机上跑完 collect_rpa_logs.ps1 后回传的 zip
  python3 cross_analysis.py --conversation-id 0123456789abcdef... \
      --host-bundle "<TOOLKIT>/temp/RpaLogCollect_<时间戳>.zip" \
      --start 2026-09-18T10:30:00 --end 2026-09-18T11:45:00

输出:
  temp/evidence_<时间戳>_<slug>/
    ├── server.json / rpa_<channel>.json / ops.json / host.json   原始证据
    ├── anchors.json      锚点在各源中的命中统计 + 跨源 ID 共现
    └── evidence.md       交叉分析证据包（含合并时间线/异常提取/主机侧专题；
                          LLM 论证入口，结论请写入 temp/analysis_*.md）
"""

import argparse
import json
import os
import re
import shutil
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# BetterYeah 业务统一北京时间(UTC+8)：SLS Unix 时间戳→展示、默认时间窗均按北京时间，
# 显式固定时区使分发包在任意时区主机上结果一致。
CST = timezone(timedelta(hours=8))


def _fmt_time_cn(time_str: str) -> str:
    """将 ISO 时间字符串转为中文格式（仅用于报告展示层）
    输入: '2026-09-23 14:30:00' 或 '2026-09-23T14:30:00+08:00'
    输出: '2026年09月23日 14:30:00'
    """
    if not time_str:
        return ''
    try:
        # 去除可能的时区后缀，取前19位 YYYY-MM-DD HH:MM:SS
        time_str = time_str[:19].replace('T', ' ')
        parts = time_str.split(' ')
        if len(parts) != 2:
            return time_str  # 异常格式保持原样
        date_part, time_part = parts
        y, m, d = date_part.split('-')
        return f"{y}年{m}月{d}日 {time_part}"
    except (ValueError, IndexError):
        return time_str  # 解析失败返回原文

SCRIPT_DIR = Path(__file__).resolve().parent
# 输出目录: 默认随包 temp/;npm CLI 安装模式(CSDBG_TEMP 已设)落 ~/.csdbg/temp，
# 避免 node_modules 升级重装时清掉分析报告。
TEMP_DIR = Path(os.environ.get("CSDBG_TEMP") or SCRIPT_DIR.parent / "temp")
sys.path.insert(0, str(SCRIPT_DIR))

sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

import ops_log_query  # noqa: E402
from exceptions import (
    categorize_sls_error, categorize_cli_error, 
    ParseError, TimeoutError, NetworkError, DataSourceError
)  # noqa: E402

# 数据源插件层（P4-10）：规范化与主机侧读取工具集中到 sources.py，
# 这里再导出，保持原有调用路径（cross_analysis.normalize_rpa / parse_host_time 等）向后兼容。
from sources import (  # noqa: E402,F401
    RPA_PATTERNS, HOST_CSV_KINDS,
    normalize_rpa, parse_host_time, _host_level, _host_rec,
    _read_host_events_csv, _read_host_keyword_csv, _read_host_text,
    load_host_bundle, _load_host_dir,
    DataSource, QueryOutcome, build_sources,
)
import fault_signatures  # noqa: E402  （P4-11 故障签名知识库）



def collect_ids(recs: List[Dict]) -> Dict[str, Counter]:
    agg: Dict[str, Counter] = {}
    for r in recs:
        for name, vals in (r.get('ids') or {}).items():
            vals = vals if isinstance(vals, list) else [vals]
            agg.setdefault(name, Counter()).update(vals)
    return agg


# ---------------------------------------------------------------- 关联分析

def anchor_hits(anchors: Dict[str, str], sources: Dict[str, List[Dict]]) -> Dict:
    """锚点 × 数据源 命中矩阵"""
    # 预构建各数据源的小写文本缓存（避免逐条 json.dumps + lower，大日志集显著提速）
    blobs = {
        s_name: [json.dumps(r, ensure_ascii=False).lower() for r in recs]
        for s_name, recs in sources.items()
    }
    matrix = {}
    for a_name, a_val in anchors.items():
        if not a_val:
            continue
        needle = a_val.lower()
        row = {}
        for s_name in sources:
            row[s_name] = sum(1 for blob in blobs[s_name] if needle in blob)
        matrix[f"{a_name}={a_val}"] = row
    return matrix


def id_cooccur(sources: Dict[str, List[Dict]]) -> Dict[str, Dict[str, int]]:
    """业务 ID 在多个数据源中的共现情况（自动交叉关联，不依赖用户输入锚点）"""
    idx: Dict[str, Dict[str, int]] = {}
    for s_name, recs in sources.items():
        agg = collect_ids(recs)
        for name, counter in agg.items():
            if name == 'hex_candidates':
                continue
            for val, c in counter.items():
                idx.setdefault(val, {'field': name, 'sources': {}})['sources'][s_name] = c
    # 只保留跨 ≥2 个数据源的 ID
    return {val: info for val, info in idx.items() if len(info['sources']) >= 2}


def detect_heartbeat_gap(sources: Dict[str, List[Dict]], min_gap: int = 300):
    """在源② RPA 记录里找 robot-health-report 心跳的最大断流间隔。
    命中返回 (gap秒, from_ts, to_ts)；不足 2 个心跳或未断流返回 None。"""
    hb = []
    for name, recs in sources.items():
        if not name.startswith('rpa:'):
            continue
        for r in recs:
            blob = (r.get('message') or '') + (r.get('extra_data') or '')
            if 'robot-health-report' not in blob and 'Robot健康度报告' not in blob:
                continue
            ts = r.get('ts')
            if ts:
                hb.append(ts)
    if len(hb) < 2:
        return None
    hb.sort()
    best = None
    for t1, t2 in zip(hb, hb[1:]):
        gap = t2 - t1
        if gap >= min_gap and (best is None or gap > best[0]):
            best = (gap, t1, t2)
    return best


def build_host_upgrade_hint(sources: Dict[str, List[Dict]]) -> str:
    """源②心跳断流但无第④源时，生成"建议补充主机侧证据"提示（P1-2 自动升级）。"""
    if 'host' in sources:
        return ''
    hit = detect_heartbeat_gap(sources)
    if not hit:
        return ''
    gap, t1, t2 = hit
    fmt = lambda ts: datetime.fromtimestamp(ts, tz=CST).strftime('%Y-%m-%d %H:%M:%S')
    mins = gap / 60
    return ("⚠ **建议补充主机侧证据（第④源）**：检测到 RPA 心跳（robot-health-report）断流 "
            f"{gap:.0f}s（约 {mins:.1f} 分钟，{fmt(t1)} → {fmt(t2)}），"
            "但本次未提供 --host-bundle / --host-events-*。\n"
            "仅凭 SLS 心跳无法区分「睡眠/休眠」与「崩溃/客户端僵死」——建议执行：\n"
            "```bash\n"
            "python scripts/host_events_query.py --equipment-id <设备ID> --start <ISO> --end <ISO>\n"
            "# 或并入证据包： cross_analysis.py ... --host-events-equipment <设备ID>\n"
            "# CLI 形态：   csdbg host-events <设备ID> --start <ISO> --end <ISO>\n"
            "```\n"
            "（设备ID可在源②记录中按 equipment 字段检索；ECD 实锤与 SLS 推断的置信度已在记录 "
            "`confidence` 字段区分）")


def extract_anomalies(sources: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
    anomalies = {}
    for s_name, recs in sources.items():
        bad = []
        for r in recs:
            lvl = (r.get('level') or '').upper()
            txt = (r.get('message') or '') + ' ' + (r.get('error_detail') or '')
            if lvl in ('ERROR', 'WARNING', 'CRITICAL') or re.search(r'fail|失败|异常|超时|timeout|abort|中止|无法', txt, re.I):
                bad.append(r)
        anomalies[s_name] = bad[:50]
    return anomalies


def correlate_ops(server_recs, rpa_recs, ops_recs) -> List[Dict]:
    """ops 运维记录与日志侧的交叉：时间窗口内该 agent/workspace 是否刚做过变更"""
    log_ids = set()
    for r in server_recs + rpa_recs:
        for name, vals in (r.get('ids') or {}).items():
            if name in ('agent_id', 'workspace_id'):
                log_ids.update(vals if isinstance(vals, list) else [vals])
    flags = []
    for o in ops_recs:
        why = []
        if o.get('agent_id') and o['agent_id'] in log_ids:
            why.append('agent_id 与日志中出现的 Agent 一致')
        if o.get('workspace_id') and o['workspace_id'] in log_ids:
            why.append('workspace_id 与日志一致')
        if why:
            flags.append({'record_id': o['record_id'], 'time': o['time'],
                          'operator': o['operator'], 'why': why,
                          'remark': (o.get('remark') or '')[:120]})
    return flags


# ---------------------------------------------------------------- 输出

def fmt_line(r: Dict) -> str:
    src = r['source']
    msg = re.sub(r'\s+', ' ', r.get('message') or r.get('remark') or '')[:150].replace('|', '/')
    lvl = (r.get('level') or '')
    warn = ' ⚠' if lvl.upper() in ('ERROR', 'WARNING', 'CRITICAL') else ''
    t = r.get('time') or ''
    return f"| {t[11:19] if len(t) > 11 else (t or '(无时间)')} | {src} | {lvl}{warn} | {msg} |"


def build_evidence_md(
    meta: Dict, sources: Dict[str, List[Dict]], matrix: Dict,
    cooccur: Dict, anomalies: Dict, ops_flags: List[Dict],
    errors_collected: List[DataSourceError] = None,
    sig_hits: List[Dict] = None,
) -> str:
    errors_collected = errors_collected or []
    L = []
    L.append(f"# 交叉分析证据包\n")
    L.append(f"- 生成时间: {_fmt_time_cn(meta['generated_at'])}")
    L.append(f"- 时间窗口: {_fmt_time_cn(meta['start'])} ~ {_fmt_time_cn(meta['end'])}")
    L.append(f"- 锚点: {json.dumps({k: v for k, v in meta['anchors'].items() if v}, ensure_ascii=False)}")
    L.append(f"- 数据源命中: " + ", ".join(f"{s}={len(recs)}条" for s, recs in sources.items()))
    L.append("")

    if meta.get('host_upgrade_hint'):
        L.append("## ⚠ 第④源升级建议\n")
        L.append(meta['host_upgrade_hint'])
        L.append("")

    if sig_hits:
        L.append("## 🧩 故障签名匹配（候选）\n")
        L.append("_基于内置知识库（templates/fault_signatures.json）的自动匹配，供论证参考——"
                 "须结合时间线人工/LLM 确认后再下结论；未命中不代表无模式（可能是新型故障）。_\n")
        for h in sig_hits:
            t = f"[{h['type']}] " if h.get('type') else ''
            match_str = ", ".join(f"{k}×{v}" for k, v in (h.get('matched') or {}).items())
            L.append(f"- **{t}{h.get('name')}**（命中: {match_str}"
                     + (f" · {h['severity_hint']}" if h.get('severity_hint') else "") + "）")
            if h.get('signature'):
                L.append("  - 特征: " + "；".join(h['signature']))
            if h.get('conclusion_template'):
                L.append(f"  - 结论模板: {h['conclusion_template']}")
        L.append("")

    if errors_collected:
        L.append("## ⚠ 数据源错误汇总\n")
        L.append(f"- 总计: {len(errors_collected)} 个错误")
        recoverable_n = sum(1 for e in errors_collected if e.recoverable)
        L.append(f"- 可重试: {recoverable_n} 个 / 不可恢复: {len(errors_collected) - recoverable_n} 个")
        by_source: Dict[str, List[DataSourceError]] = {}
        for e in errors_collected:
            by_source.setdefault(e.source or '(未知源)', []).append(e)
        for src, errs in sorted(by_source.items()):
            L.append(f"\n### {src}（{len(errs)} 个错误）\n")
            for e in errs:
                flag = "🔄 可重试" if e.recoverable else "❌ 不可恢复"
                L.append(f"- **{e.__class__.__name__}** [{flag}]: {e}")
        if recoverable_n:
            L.append("\n> 提示：标记为「可重试」的错误多为认证过期/超时/网络抖动，"
                     "重新执行或刷新凭据后可能恢复；「不可恢复」错误（配额耗尽/解析失败）需人工介入。")
        L.append("")

    L.append("## 1. 锚点命中矩阵（锚点 × 数据源 → 命中条数）\n")
    L.append("| 锚点 | " + " | ".join(sources.keys()) + " |")
    L.append("|---" * (len(sources) + 1) + "|")
    for a, row in matrix.items():
        L.append(f"| {a} | " + " | ".join(str(row.get(s, 0)) for s in sources) + " |")
    L.append("")

    L.append("## 2. 自动交叉关联（同一业务 ID 出现在 ≥2 个数据源）\n")
    if cooccur:
        L.append("| ID | 字段 | " + " | ".join(sources.keys()) + " |")
        L.append("|---" * (len(sources) + 2) + "|")
        for val, info in sorted(cooccur.items(), key=lambda kv: -sum(kv[1]['sources'].values()))[:20]:
            L.append(f"| `{val}` | {info['field']} | " +
                     " | ".join(str(info['sources'].get(s, '-')) for s in sources) + " |")
    else:
        L.append("_未发现跨源共现的业务 ID（各源事件可能不属于同一条链路）_")
    L.append("")

    L.append("## 3. 多源合并时间线（最多 300 条，异常加 ⚠）\n")
    merged = []
    for recs in sources.values():
        merged += recs
    merged.sort(key=lambda r: r.get('ts') or 0)
    L.append("| 时间 | 来源 | 级别 | 内容 |")
    L.append("|---|---|---|---|")
    for r in merged[:300]:
        L.append(fmt_line(r))
    L.append("")

    # 第④源专题：主机侧原始读数（冻结/崩溃/睡眠/网络 四选一的判据来源）
    host_recs = sources.get('host') or []
    if host_recs or meta.get('host_summary'):
        L.append("## 3b. 主机/IP 侧证据（第④源）\n")
        if meta.get('host'):
            L.append(f"- 主机: `{meta['host']}`")
        by_kind = Counter(r.get('host_kind') for r in host_recs)
        L.append(f"- 条数: {len(host_recs)}  " +
                 " ".join(f"`{k}`={c}" for k, c in by_kind.most_common()))
        if meta.get('host_bundle'):
            L.append(f"- 证据包: `{meta['host_bundle']}`")
        if meta.get('host_summary'):
            L.append("\n**summary.txt（主机 / 开机时间 / 每日事件计数）**：\n")
            L.append("```")
            L.extend(meta['host_summary'].splitlines()[:40])
            L.append("```")
        for kind, title in (('power', '关机/开机/电源'), ('crash-qn', '千牛/RPA 崩溃'),
                            ('crash', '应用崩溃'), ('net', '网络')):
            rows = [r for r in host_recs if r.get('host_kind') == kind][:15]
            if not rows:
                continue
            L.append(f"\n**{title}（`{kind}`，最多 15 条）**：\n")
            for r in rows:
                L.append(f"- `{_fmt_time_cn(r['time'])}` [{r.get('level','')}] {r['message'][:180]}")
        # 电源/重启/崩溃专项抓取（host_events_query.py：SLS 心跳重建 / ECD 事件日志）
        ev = [r for r in host_recs if r.get('host_source') in ('sls', 'ecd')]
        if ev:
            tag = meta.get('host_events') or '专项抓取'
            L.append(f"\n**电源 / 重启 / 崩溃事件（{tag}）**：\n")
            for kind, title in (('restart', '重启/开机'), ('power', '睡眠/断流'),
                                ('crash', '崩溃/RPA重启'), ('state', '状态切换')):
                rows = [r for r in ev if r.get('host_kind') == kind][:15]
                if not rows:
                    continue
                L.append(f"- **{title}（`{kind}`，{len(rows)} 条）**")
                for r in rows:
                    L.append(f"  - `{_fmt_time_cn(r['time'])}` [{r.get('level','')}] {r['message'][:200]}")
            L.append("")
        L.append("")

    L.append("## 4. 各源异常提取\n")
    for s, bad in anomalies.items():
        L.append(f"### {s} — {len(bad)} 条异常")
        for r in bad[:15]:
            L.append(f"- `{_fmt_time_cn(r.get('time',''))}` [{r.get('level','')}] " +
                     re.sub(r'\s+', ' ', (r.get('message') or ''))[:180])
        L.append("")

    L.append("## 5. ops 运维操作关联（变更 ↔ 问题窗口）\n")
    if ops_flags:
        for f in ops_flags:
            L.append(f"- ⚠ {_fmt_time_cn(f['time'])} 操作人 {f['operator']}: {f['remark']}  ({'; '.join(f['why'])})")
    else:
        L.append("_问题时间窗口内未发现与涉事 Agent/工作空间相关的运维变更记录_")
    L.append("")

    L.append("## 6. ops 运维记录（本窗口全量）\n")
    for o in sources.get('ops', [])[:30]:
        L.append(f"- `{_fmt_time_cn(o['time'])}` [{o['operator']}] {str(o['remark'])[:120]}")
    if not sources.get('ops'):
        L.append("_无_")
    L.append("")

    L.append("---")
    L.append("**下一步**: 由分析者（LLM/人工）基于本证据包交叉论证，"
             "将问题结论写入 `temp/analysis_<时间>-<简述>.md`（模板见 skill/cs-log-cross/SKILL.md）。")
    return "\n".join(L)


# ---------------------------------------------------------------- 主流程

def _smart_window(conversation_id: str, workspace: str = None):
    """有会话锚点且未显式给时间窗时，从会话首末消息推断合理窗口（±10min），
    并限制在客服排班典型时段 08:00-23:59，避免默认"今天 00:00~现在"在夜间
    空窗时段查出 0 条被误读为异常。失败返回 None（调用方回退默认窗口）。"""
    try:
        cli_args = (['--workspace', workspace] if workspace else []) + \
                   ['conversation', 'records', conversation_id, '--page-size', '50']
        d = ops_log_query._run_cs_cli(cli_args)
        recs = (d or {}).get('data') or []
        times = [r.get('message_time') for r in recs if r.get('message_time')]
        if not times:
            return None
        first_dt = datetime.fromisoformat(min(times))
        last_dt = datetime.fromisoformat(max(times))
        first_dt = first_dt if first_dt.tzinfo else first_dt.replace(tzinfo=CST)
        last_dt = last_dt if last_dt.tzinfo else last_dt.replace(tzinfo=CST)
        start = first_dt - timedelta(minutes=10)
        end = last_dt + timedelta(minutes=10)
        # 限制在 08:00-23:59（典型客服排班），夜间无边话务不纳入窗口
        start = max(start, start.replace(hour=8, minute=0, second=0, microsecond=0))
        end = min(end, end.replace(hour=23, minute=59, second=59, microsecond=0))
        if end <= start:
            return None
        return (start.isoformat(timespec='seconds'), end.isoformat(timespec='seconds'))
    except Exception:
        return None


def run(args) -> Path:
    now = datetime.now(tz=CST)
    if not (args.start and args.end) and args.conversation_id:
        win = _smart_window(args.conversation_id, args.workspace)
        if win:
            if not args.start:
                args.start = win[0]
            if not args.end:
                args.end = win[1]
            print(f"⏱ 自动时间窗（会话首末消息 ±10min，限 08:00-23:59）: {args.start} ~ {args.end}")
    if not args.start:
        args.start = (now.replace(hour=0, minute=0, second=0, microsecond=0)).isoformat(timespec='seconds')
    if not args.end:
        args.end = now.isoformat(timespec='seconds')

    anchors = {
        'conversation_id': args.conversation_id,
        'trace_id': args.trace_id,
        'request_id': args.request_id,
        'dispatch_id': args.dispatch_id,
        'keyword': args.query,
    }
    slug = (args.conversation_id or args.trace_id or args.request_id or
            args.dispatch_id or re.sub(r'\W+', '', args.query or 'window') or 'window')[:12]
    out_dir = TEMP_DIR / f"evidence_{now.strftime('%Y%m%d_%H%M%S')}_{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)

    sources: Dict[str, List[Dict]] = {}
    host_summary = ''
    host_name = ''
    errors_collected: List[DataSourceError] = []

    # ---- 数据源插件（P4-10）：前三源并行 → 主机侧串行
    plugins = build_sources(args)
    core_plugins = [p for p in plugins if p.order < 40]
    host_plugins = [p for p in plugins if p.order >= 40]

    def _merge_outcome(oc: QueryOutcome):
        nonlocal host_summary, host_name
        errors_collected.extend(oc.errors)
        for line in oc.log:
            print(line)
        for fname, obj in oc.files:
            (out_dir / fname).write_text(
                json.dumps(obj, ensure_ascii=False, indent=1), encoding='utf-8')
        if oc.merge == 'host-merge':
            # 主机侧：bundle 先入，事件按 (ts,kind,message) 去重补新；两者共写一个 host.json
            existing = {(r.get('ts'), r.get('host_kind'), r.get('message'))
                        for r in sources.get('host', [])}
            for _, recs in oc.entries:
                new = [r for r in recs
                       if (r.get('ts'), r.get('host_kind'), r.get('message')) not in existing]
                if new:
                    sources.setdefault('host', []).extend(new)
            if sources.get('host'):
                sources['host'].sort(key=lambda r: r.get('ts') or 0)
                (out_dir / 'host.json').write_text(
                    json.dumps(sources['host'], ensure_ascii=False, indent=1), encoding='utf-8')
            host_name = host_name or oc.meta.get('host', '')
            host_summary = host_summary or oc.meta.get('summary', '')
        else:
            for key, recs in oc.entries:
                sources[key] = recs

    print("▶ [1-3/4] 并行查询服务端/RPA/ops 日志...")
    with ThreadPoolExecutor(max_workers=max(1, len(core_plugins))) as executor:
        futures = [(p, executor.submit(p.run_query, args, out_dir)) for p in core_plugins]
        for p, fut in futures:
            try:
                _merge_outcome(fut.result())
            except Exception as e:   # 插件内部已捕获；此兜底保证主流程不中断
                err = categorize_sls_error(e, p.name)
                errors_collected.append(err)
                print(f"  ❌ {p.label}查询失败: {err} (source={err.source}, recoverable={err.recoverable})")
                sources.setdefault(p.name, [])

    # ---- 主机/IP 侧（第④源插件，可选；串行执行）
    if not host_plugins:
        print("▶ [4/4] 主机/IP 侧证据 — 未提供 --host-bundle / --host-events-*，跳过"
              "（④ 的 SLS 面 hostname/出口IP/心跳 已含在源②；需要主机本地面时补 "
              "--host-bundle，或对目标设备用 --host-events-equipment 一键抓电源/重启/崩溃事件）")
    for p in host_plugins:
        if p.header:
            print(p.header)
        try:
            _merge_outcome(p.run_query(args, out_dir))
        except Exception as e:
            err = categorize_cli_error(e, p.name)
            errors_collected.append(err)
            print(f"  ❌ {p.label}失败: {err} (source={err.source}, recoverable={err.recoverable})")

    # ---- 交叉分析
    matrix = anchor_hits(anchors, sources)
    cooccur = id_cooccur(sources)
    anomalies = extract_anomalies(sources)
    ops_flags = correlate_ops(sources.get('server', []),
                              [r for k, v in sources.items() if k.startswith('rpa:') for r in v],
                              sources.get('ops', []))

    upgrade_hint = build_host_upgrade_hint(sources)
    if upgrade_hint:
        print("  ⚠ 检测到 RPA 心跳断流且无第④源证据 → evidence.md 已附「第④源升级建议」")

    sig_hits = fault_signatures.match_signatures(sources)
    if sig_hits:
        brief = "; ".join(f"[{h['type'] or h['id']}] {h['name']}" for h in sig_hits[:3])
        print(f"  🧩 故障签名匹配（候选）: {brief}" + (" …" if len(sig_hits) > 3 else ""))

    meta = {
        'generated_at': now.isoformat(timespec='seconds'),
        'start': args.start, 'end': args.end,
        'anchors': anchors,
        'source_stats': {s: len(recs) for s, recs in sources.items()},
        'host_bundle': args.host_bundle or '',
        'host_events': ('equipment=' + (args.host_events_equipment or '')
                        + (' desktop=' + args.host_events_desktop
                           if args.host_events_desktop else '')).strip() or '',
        'host': host_name,
        'host_summary': host_summary,
        'host_upgrade_hint': upgrade_hint,
        'signature_hits': [h['id'] for h in sig_hits],
    }
    (out_dir / 'anchors.json').write_text(
        json.dumps({'meta': meta, 'anchor_matrix': matrix,
                    'cross_source_ids': cooccur, 'ops_flags': ops_flags},
                   ensure_ascii=False, indent=1), encoding='utf-8')

    evidence = build_evidence_md(meta, sources, matrix, cooccur, anomalies, ops_flags,
                                 errors_collected, sig_hits)
    (out_dir / 'evidence.md').write_text(evidence, encoding='utf-8')

    _write_evidence_meta(out_dir, meta, sources, errors_collected)
    try:
        import telemetry
        telemetry.log_usage('cs-log-cross', anchors, list(sources.keys()), not errors_collected)
    except Exception:
        pass

    _archive_old_evidence()
    print(f"\n📦 证据包已生成: {out_dir}")
    print(f"   → 请基于 evidence.md 交叉论证，将结论写入 {TEMP_DIR}/analysis_*.md")
    return out_dir


def _write_evidence_meta(out_dir: Path, meta: Dict, sources: Dict[str, List[Dict]],
                         errors: List[DataSourceError]):
    """证据包元数据（creator/锚点/标签/状态）：供批量审计与后续结论回填。"""
    try:
        import getpass
        import socket
        try:
            creator = (getpass.getuser() or 'unknown') + '@' + socket.gethostname()
        except Exception:
            creator = os.environ.get('USERNAME') or os.environ.get('USER') or 'unknown'
        anchors_used = {k: v for k, v in (meta.get('anchors') or {}).items() if v}
        tags = sorted(anchors_used.keys()) + sorted(sources.keys())
        if meta.get('host_upgrade_hint'):
            tags.append('第④源待补')
        doc = {
            'creator': creator,
            'created_at': meta.get('generated_at'),
            'anchors': anchors_used,
            'tags': tags,
            'status': 'new',        # new → analyzed：结论写入 analysis_*.md 后可回填 status/conclusion
            'conclusion': '',
            'sources': {s: len(r) for s, r in sources.items()},
            'errors': len(errors or []),
        }
        (out_dir / 'meta.json').write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')
    except Exception:
        pass


def _archive_old_evidence(keep: int = None):
    """证据包磁盘控制：只保留最新 keep 个 evidence_* 目录，更旧的自动归档为同名 .zip。
    keep 默认 5，可用环境变量 CSDBG_EVIDENCE_KEEP 覆盖；CSDBG_NO_ARCHIVE=1 关闭。
    失败静默跳过（归档是运维便利，不应阻断主流程）。"""
    if os.environ.get('CSDBG_NO_ARCHIVE'):
        return
    if keep is None:
        try:
            keep = int(os.environ.get('CSDBG_EVIDENCE_KEEP', '5'))
        except ValueError:
            keep = 5
    try:
        dirs = sorted((d for d in TEMP_DIR.glob('evidence_*') if d.is_dir()),
                      key=lambda d: d.stat().st_mtime, reverse=True)
        for old in dirs[keep:]:
            zip_path = old.with_suffix('.zip')
            shutil.make_archive(str(old), 'zip', str(old))
            if zip_path.exists():
                shutil.rmtree(old)
                print(f"🗜 旧证据包已归档: {old.name} → {zip_path.name}")
    except Exception as e:
        print(f"⚠ 证据包归档跳过（{e}）")


def main():
    p = argparse.ArgumentParser(description='多方日志交叉分析证据包生成器')
    p.add_argument('--conversation-id', help='会话 ID（首选锚点）')
    p.add_argument('--trace-id', help='服务端 otelTraceID')
    p.add_argument('--request-id', help='ws_request_id')
    p.add_argument('--dispatch-id', help='RPA 下发 dispatch_id')
    p.add_argument('--query', help='关键词锚点')
    # 渠道名不设硬编码 choices：以 channels.json 配置为准（rpa_log_query.query() 内有运行时校验）
    p.add_argument('--channel', help='仅查询指定 RPA 渠道（默认全渠道）')
    p.add_argument('--dev', action='store_true', help='RPA 查询开发环境 logstore（--dev 透传）')
    p.add_argument('--workspace', help='ops 记录按工作空间过滤')
    p.add_argument('--agent', help='ops 记录按 Agent 过滤')
    p.add_argument('--host-bundle', dest='host_bundle',
                   help='第④源（主机/IP 侧）：collect_rpa_logs.ps1 回传的 zip / 解压目录 / '
                        'ECD 远程拉起的文本输出')
    p.add_argument('--host-events-equipment', dest='host_events_equipment',
                   help='第④源专项：目标设备 ID（equipment_id），自动抓取该设备 '
                        '电源/重启/崩溃 事件（ECD 实锤优先，SLS 心跳重建兜底）')
    p.add_argument('--host-events-desktop', dest='host_events_desktop',
                   help='第④源专项：ECD 云电脑 desktopId（配合 --host-events-equipment '
                        '或单独使用，走 RunCommand 拉主机事件日志实锤）')
    p.add_argument('--host-events-min-gap', dest='host_events_min_gap', type=int, default=300,
                   help='心跳断流事件阈值秒（默认 300）')
    p.add_argument('--host-events-limit', dest='host_events_limit', type=int, default=5000,
                   help='host-events 心跳条数上限（默认 5000，独立于 --limit）')
    p.add_argument('--level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='服务端日志级别过滤')
    p.add_argument('--start', help='开始时间（缺省=今天 00:00）')
    p.add_argument('--end', help='结束时间（缺省=现在）')
    p.add_argument('--limit', type=int, default=1000, help='日志类数据源单源上限（默认 1000）')
    p.add_argument('--ops-limit', type=int, default=200, help='ops 记录上限（默认 200）')
    args = p.parse_args()
    run(args)


if __name__ == '__main__':
    main()
