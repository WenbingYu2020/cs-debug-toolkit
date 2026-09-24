#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sources.py — 数据源插件层（P4-10 插件化数据源）

设计目标：**新增数据源 = 实现一个 DataSource 子类 + 在 build_sources() 注册一行**，
不再改 cross_analysis.py 的主流程。

结构：
  · QueryOutcome   —— 插件统一返回结构（entries/files/errors/log/meta）
  · DataSource     —— 抽象基类（name/order/run_query）
  · ServerLogSource / RPALogSource / OpsSource / HostBundleSource / HostEventsSource
  · build_sources(args) —— 注册表：按参数裁剪出本次要跑的插件列表

规范化与主机侧读取工具（normalize_rpa / parse_host_time / load_host_bundle 等）
也从本模块导出；cross_analysis.py 仍按原路径再导出以保持向后兼容。
"""
import csv
import json
import re
import zipfile
from abc import ABC, abstractmethod
from collections import Counter  # noqa: F401  (供调用方复用)
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# BetterYeah 业务统一北京时间(UTC+8)
CST = timezone(timedelta(hours=8))

from server_log_query import ServerLogQuery, ID_PATTERNS  # noqa: E402
from rpa_log_query import RPALogQuery  # noqa: E402
import ops_log_query  # noqa: E402
import host_events_query  # noqa: E402
from exceptions import categorize_sls_error, categorize_cli_error, DataSourceError  # noqa: E402

# RPA 日志的消息格式使用缩写键（conv= / task= / equipment=）
RPA_PATTERNS = {
    'conversation_id': re.compile(r'conv[ =:"]+([a-f0-9]{16,64})', re.I),
    'task_id': re.compile(r'task[ =:"]+([a-f0-9]{16,64})', re.I),
}


# ---------------------------------------------------------------- 规范化

def normalize_rpa(raw: List[Dict], channel: str) -> List[Dict]:
    out = []
    for r in raw:
        try:
            ts = int(r.get('__time__', 0) or 0)
        except (TypeError, ValueError):   # 脏时间戳容错
            ts = 0
        msg = r.get('message', '')
        ids = {}
        for k, field in (('conversation_id', 'extra_conversation_id'),
                         ('equipment_id', 'extra_equipment_id')):
            v = r.get(field) or ''
            if v:
                ids.setdefault(k, []).append(v)
        # 从 message 正文提取（先缩写格式，再通用格式）
        for name, pat in RPA_PATTERNS.items():
            found = pat.findall(msg)
            if found:
                ids.setdefault(name, []).extend(found)
        for name, pat in ID_PATTERNS.items():
            found = pat.findall(msg)
            if found:
                ids.setdefault(name, []).extend(found)
        ids = {k: sorted(set(v)) for k, v in ids.items()}
        m = re.findall(r'\b[0-9a-f]{32}\b', msg)
        typed = {v for vals in ids.values() for v in vals}
        rest = [h for h in m if h not in typed]
        if rest:
            ids['hex_candidates'] = sorted(set(rest))
        out.append({
            'source': f'rpa:{channel}',
            'ts': ts,
            'time': datetime.fromtimestamp(ts, tz=CST).strftime('%Y-%m-%d %H:%M:%S') if ts else '',
            'level': r.get('level', ''),
            'module': r.get('module', ''),
            'function': r.get('function', ''),
            'message': msg,
            'error_detail': r.get('error_detail', ''),
            'ids': ids,
        })
    return out


# ------------------------------------------------- 第④源: 主机/IP 侧（主机本地证据）

# collect_rpa_logs.ps1 工件 → (类别, 中文标签)。事件类 CSV 列固定为 Time,Id,Provider,Level,Message
HOST_CSV_KINDS = {
    '01_system_power_boot.csv':         ('power',    '关机/开机/电源'),
    '02_system_network.csv':            ('net',      '网络'),
    '03_system_service_rpa_qn.csv':     ('svc',      '服务(RPA/千牛)'),
    '03b_system_service_all_crash.csv': ('svc-all',  '服务(全部异常)'),
    '04_app_crash_all.csv':             ('crash',    '应用崩溃'),
    '04b_app_crash_qianniu_rpa.csv':    ('crash-qn', '千牛/RPA 崩溃'),
    '05_power_recent60.csv':            ('power60',  '电源近60条'),
}

# PowerShell Export-Csv 写出的 DateTime 随机器区域设置变化，这里逐个试
_PS_TIME_FORMATS = (
    '%Y/%m/%d %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M', '%Y-%m-%d %H:%M',
    '%m/%d/%Y %I:%M:%S %p', '%m/%d/%Y %H:%M:%S', '%m/%d/%Y %I:%M %p',
    '%Y-%m-%dT%H:%M:%S', '%Y/%m/%d %H:%M:%S.%f',
)

# 文本行首时间戳：'2026-09-18 18:01:23' / '2026/9/18 18:01' / '[09-18 18:01:23]'
_LINE_TS_FULL = re.compile(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})[ T](\d{1,2}:\d{2}(?::\d{2})?)')

_LEVEL_MAP = {
    '错误': 'ERROR', '严重': 'CRITICAL', '警告': 'WARNING', '信息': 'INFO', '详细': 'VERBOSE',
    'error': 'ERROR', 'critical': 'CRITICAL', 'warning': 'WARNING',
    'information': 'INFO', 'verbose': 'VERBOSE',
}


def parse_host_time(s: str) -> Tuple[str, float]:
    """容错解析 Windows 事件时间。返回 ('YYYY-MM-DD HH:MM:SS', epoch秒)；解析不出返回 (原文, 0)。"""
    s = (s or '').strip()
    if not s:
        return '', 0.0
    for f in _PS_TIME_FORMATS:
        try:
            dt = datetime.strptime(s, f)
            return dt.strftime('%Y-%m-%d %H:%M:%S'), dt.timestamp()
        except ValueError:
            continue
    m = _LINE_TS_FULL.search(s)
    if m:
        for sep in ('/', '-'):
            try:
                dt = datetime.strptime(m.group(1).replace('/', sep) + ' ' + m.group(2),
                                       f'%Y{sep}%m{sep}%d ' + ('%H:%M:%S' if m.group(2).count(':') == 2 else '%H:%M'))
                return dt.strftime('%Y-%m-%d %H:%M:%S'), dt.timestamp()
            except ValueError:
                continue
    return s, 0.0


def _host_level(raw: str) -> str:
    r = (raw or '').strip()
    return _LEVEL_MAP.get(r, _LEVEL_MAP.get(r.lower(), r.upper()[:12]))


def _host_rec(kind: str, time_s: str, ts: float, level: str, message: str,
              host: str = '') -> Dict:
    return {
        'source': 'host',
        'host_kind': kind,
        'host': host,
        'time': time_s,
        'time_tz': 'Asia/Shanghai',
        'ts': ts,
        'level': level,
        'message': message,
        'ids': {},
    }


def _read_host_events_csv(f: Path, kind: str, label: str, host: str) -> List[Dict]:
    out = []
    with open(f, 'r', encoding='utf-8-sig', errors='replace', newline='') as fh:
        for row in csv.DictReader(fh):
            t, ts = parse_host_time(row.get('Time') or '')
            msg = re.sub(r'\s+', ' ', row.get('Message') or '').strip()
            prov = (row.get('Provider') or '').strip()
            eid = (row.get('Id') or '').strip()
            out.append(_host_rec(kind, t, ts, _host_level(row.get('Level')),
                                 f"[{label}] {prov} ID={eid} {msg}".strip(), host))
    return out


def _read_host_keyword_csv(f: Path, host: str) -> List[Dict]:
    out = []
    with open(f, 'r', encoding='utf-8-sig', errors='replace', newline='') as fh:
        for row in csv.DictReader(fh):
            line = re.sub(r'\s+', ' ', row.get('Text') or '').strip()
            t, ts = parse_host_time(line)
            loc = f"{row.get('File', '')}:{row.get('LineNo', '')}"
            out.append(_host_rec('kw', t, ts, '', f"[客户端日志关键词] {loc} {line}", host))
    return out


def _read_host_text(text: str, host: str, tag: str = '') -> List[Dict]:
    """把远程拉起（ecd-exec）的文本输出按行收进时间线：只收行首带时间戳的行。"""
    out = []
    for raw in text.splitlines():
        t, ts = parse_host_time(raw)
        if not ts:
            continue
        out.append(_host_rec('text', t, ts, '', f"[{tag or '主机文本'}] {raw.strip()[:200]}", host))
    return out


def load_host_bundle(bundle: str, out_dir: Path) -> Tuple[List[Dict], str, str]:
    """载入第④源证据。支持三种形态：
      · collect_rpa_logs.ps1 产出的 .zip（自动解到 evidence/host_bundle/）
      · 已解压的目录
      · 纯文本（ECD 远程拉起 PowerShell 的 stdout / --save 落盘文件）
    返回 (记录列表, summary.txt 全文, 主机名)。"""
    p = Path(bundle).expanduser()
    if not p.exists():
        raise FileNotFoundError(f'主机侧证据不存在: {p}')

    if p.is_file() and p.suffix.lower() not in ('.txt', '.log'):
        work = out_dir / 'host_bundle'
        work.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                parts = Path(n).parts
                if n.startswith('/') or '..' in parts:      # 防目录穿越
                    continue
                z.extract(n, work)
        return _load_host_dir(work)

    if p.is_dir():
        return _load_host_dir(p)

    text = p.read_text(encoding='utf-8-sig', errors='replace')
    return _read_host_text(text, '', p.stem), text, ''


def _load_host_dir(root: Path) -> Tuple[List[Dict], str, str]:
    recs: List[Dict] = []
    summary = ''
    host = ''
    # zip 里可能多套一层目录：向下找一层含 summary.txt 或 01_*.csv 的目录
    if not any((root / n).exists() for n in ('summary.txt', '01_system_power_boot.csv')):
        subs = [d for d in root.iterdir() if d.is_dir()]
        for d in subs:
            if (d / 'summary.txt').exists() or (d / '01_system_power_boot.csv').exists():
                root = d
                break

    for name, (kind, label) in HOST_CSV_KINDS.items():
        f = root / name
        if f.exists():
            recs += _read_host_events_csv(f, kind, label, host)
    kw = root / '06_log_keyword_hits.csv'
    if kw.exists():
        recs += _read_host_keyword_csv(kw, host)

    for cand in ('summary.txt', 'summary.TXT'):
        sf = root / cand
        if sf.exists():
            summary = sf.read_text(encoding='utf-8-sig', errors='replace')
            m = re.search(r'^host\s*:\s*(\S+)', summary, re.M)
            if m:
                host = m.group(1)
            break

    # 附加文本读数（如远程拉起另存的 out.txt）
    for extra in sorted(root.glob('*.txt')):
        if extra.name.lower() == 'summary.txt':
            continue
        recs += _read_host_text(extra.read_text(encoding='utf-8-sig', errors='replace'), host, extra.stem)

    for r in recs:
        r['host'] = host
    recs.sort(key=lambda r: r['ts'] or 0)
    return recs, summary, host


# ---------------------------------------------------------------- 插件接口

@dataclass
class QueryOutcome:
    """插件统一返回结构。主流程据此合并 sources / 落盘证据 / 收集错误与日志。"""
    name: str                                                    # 插件名（错误归属/日志用）
    entries: List[Tuple[str, List[Dict]]] = field(default_factory=list)   # (sources 键, 记录)
    files: List[Tuple[str, Any]] = field(default_factory=list)   # 待写 JSON 证据文件 (文件名, 可序列化对象)
    errors: List[DataSourceError] = field(default_factory=list)
    log: List[str] = field(default_factory=list)                 # 终端输出行
    meta: Dict = field(default_factory=dict)                     # 附加元数据（host/summary 等）
    merge: str = 'replace'                                       # 'replace' | 'host-merge'


class DataSource(ABC):
    """数据源插件基类：新增数据源 = 实现本类 + 在 build_sources() 注册一行。"""
    name: str = ''
    label: str = ''
    order: int = 50          # <40 归并行批次（前三源），>=40 为串行的主机侧阶段
    header: str = ''         # 串行阶段的执行前标题（并行批次用统一标题）

    @abstractmethod
    def run_query(self, args, out_dir: Path) -> QueryOutcome:
        """执行查询。内部应捕获异常并归类进 QueryOutcome.errors（不向主流程抛）。"""


# ---------------------------------------------------------------- 各源实现

class ServerLogSource(DataSource):
    name = 'server'
    label = '服务端日志'
    order = 10

    def run_query(self, args, out_dir: Path) -> QueryOutcome:
        oc = QueryOutcome(name=self.name)
        try:
            sq = ServerLogQuery()
            recs = sq.query(
                start_time=args.start, end_time=args.end,
                conversation_id=args.conversation_id, trace_id=args.trace_id,
                request_id=args.request_id, dispatch_id=args.dispatch_id,
                query_text=args.query, level=args.level, limit=args.limit, quiet=True,
            )
            oc.entries.append(('server', recs))
            oc.files.append(('server.json', recs))
            oc.log.append(f"  ✅ [1/4] 服务端: {len(recs)} 条")
        except DataSourceError as e:
            oc.errors.append(e)
            oc.log.append(f"  ❌ 服务端查询失败: {e} (source={e.source}, recoverable={e.recoverable})")
            oc.entries.append(('server', []))
        except Exception as e:
            err = categorize_sls_error(e, "server-log")
            oc.errors.append(err)
            oc.log.append(f"  ❌ 服务端查询失败: {err} (source={err.source}, recoverable={err.recoverable})")
            oc.entries.append(('server', []))
        return oc


class RPALogSource(DataSource):
    """RPA 端日志：4 渠道相互独立 → 渠道级并行（上限 4，每渠道独立 LogClient）。"""
    name = 'rpa'
    label = 'RPA 端日志'
    order = 20

    def run_query(self, args, out_dir: Path) -> QueryOutcome:
        oc = QueryOutcome(name=self.name)
        results: Dict[str, List[Dict]] = {}
        channels: List[str] = []
        try:
            rq = RPALogQuery()
            channels = [args.channel] if args.channel else list(rq.config['channels'].keys())

            def _one(ch):
                try:
                    # 每渠道独立 RPALogQuery 实例（独立 LogClient），避免共享客户端的并发不确定性
                    rq_ch = RPALogQuery()
                    raw = rq_ch.query(channel=ch, start_time=args.start, end_time=args.end,
                                      conversation_id=args.conversation_id,
                                      query_text=args.query, limit=args.limit,
                                      dev=args.dev, quiet=True)
                    return ch, normalize_rpa(raw, ch), None
                except DataSourceError as e:
                    return ch, None, e
                except Exception as e:
                    return ch, None, categorize_sls_error(e, f"rpa-log:{ch}")

            with ThreadPoolExecutor(max_workers=min(4, max(1, len(channels)))) as ex:
                for ch, recs, err in ex.map(_one, channels):
                    if err is not None:
                        oc.errors.append(err)
                    else:
                        results[ch] = recs
        except DataSourceError as e:
            oc.errors.append(e)
        except Exception as e:
            oc.errors.append(categorize_sls_error(e, "rpa-log"))

        for e in oc.errors:
            src = e.source or ''
            ch = src.split(':', 1)[1] if src.startswith('rpa-log:') else ''
            label = f"渠道 {ch} 查询失败" if ch else "RPA 查询失败"
            oc.log.append(f"  ❌ {label}: {e} (source={e.source}, recoverable={e.recoverable})")
        if results:
            oc.log.append("  ✅ [2/4] RPA 端:")
            for ch, recs in results.items():
                oc.entries.append((f'rpa:{ch}', recs))
                oc.files.append((f'rpa_{ch}.json', recs))
                oc.log.append(f"      - {ch}: {len(recs)} 条")
        else:
            oc.log.append("  ⚠ [2/4] RPA 端: 无数据")
        return oc


class OpsSource(DataSource):
    name = 'ops'
    label = 'ops 运维日志'
    order = 30

    def run_query(self, args, out_dir: Path) -> QueryOutcome:
        oc = QueryOutcome(name=self.name)
        try:
            ops = ops_log_query.list_records(
                start=args.start, end=args.end,
                workspace=args.workspace, agent=args.agent,
                keyword=args.query, limit=args.ops_limit, quiet=True,
            )
            if args.conversation_id:
                conv_in_ops = [o for o in ops if args.conversation_id in (o.get('remark') or '')]
                ops = (conv_in_ops or ops)
            oc.entries.append(('ops', ops))
            oc.files.append(('ops.json', ops))
            oc.log.append(f"  ✅ [3/4] ops: {len(ops)} 条")
        except DataSourceError as e:
            oc.errors.append(e)
            oc.log.append(f"  ❌ ops 查询失败: {e} (source={e.source}, recoverable={e.recoverable})")
        except Exception as e:
            err = categorize_cli_error(e, "ops-record")
            oc.errors.append(err)
            oc.log.append(f"  ❌ ops 查询失败: {err} (source={err.source}, recoverable={err.recoverable})")
        return oc


class HostBundleSource(DataSource):
    """主机本地证据（collect_rpa_logs.ps1 回传 zip / 目录 / 文本）。"""
    name = 'host-bundle'
    label = '主机/IP 侧证据'
    order = 40
    header = '▶ [4/4] 主机/IP 侧证据 (主机本地 Windows 事件日志 / 客户端日志)'

    def run_query(self, args, out_dir: Path) -> QueryOutcome:
        oc = QueryOutcome(name=self.name, merge='host-merge')
        try:
            host_recs, host_summary, host_name = load_host_bundle(args.host_bundle, out_dir)
            oc.entries.append(('host', host_recs))
            oc.meta = {'host': host_name, 'summary': host_summary}
            kind_stat = Counter(r.get('host_kind') for r in host_recs)
            oc.log.append(f"  ✅ {len(host_recs)} 条" +
                          (f"  ({host_name})" if host_name else "") +
                          ("  " + " ".join(f"{k}={c}" for k, c in kind_stat.most_common())
                           if host_recs else ""))
        except DataSourceError as e:
            oc.errors.append(e)
            oc.log.append(f"  ❌ 主机侧证据载入失败: {e} (source={e.source}, recoverable={e.recoverable})")
        except Exception as e:
            err = categorize_cli_error(e, "host-bundle")
            oc.errors.append(err)
            oc.log.append(f"  ❌ 主机侧证据载入失败: {err} (source={err.source}, recoverable={err.recoverable})")
        return oc


class HostEventsSource(DataSource):
    """目标设备 电源/重启/崩溃 事件专项抓取（第④源，ECD 实锤优先 / SLS 心跳兜底）。"""
    name = 'host-events'
    label = '目标设备事件'
    order = 41
    header = '▶ [4/4b] 目标设备电源/重启/崩溃事件 (host_events_query.py：ECD 实锤优先 / SLS 心跳兜底)'

    def run_query(self, args, out_dir: Path) -> QueryOutcome:
        oc = QueryOutcome(name=self.name, merge='host-merge')
        try:
            ev_recs, ev_meta = host_events_query.pull_host_events(
                equipment_id=args.host_events_equipment, desktop_id=args.host_events_desktop,
                start=args.start, end=args.end, channel=args.channel,
                min_gap=args.host_events_min_gap, limit=args.host_events_limit, quiet=True)
            oc.entries.append(('host', ev_recs))
            oc.meta = {'host': ev_meta.get('host', ''), 'summary': ev_meta.get('summary', '')}
            if ev_recs:
                kind_stat = Counter(r.get('host_kind') for r in ev_recs)
                oc.log.append(f"  ✅ {len(ev_recs)} 条事件" +
                              (f"  ({ev_meta.get('host','')})" if ev_meta.get('host') else "") +
                              ("  " + " ".join(f"{k}={c}" for k, c in kind_stat.most_common())
                               if ev_recs else ""))
            else:
                oc.log.append("  ⚠ 未抓到事件（设备无心跳或无 ECD 权限）")
        except DataSourceError as e:
            oc.errors.append(e)
            oc.log.append(f"  ❌ 主机电源/重启/崩溃事件抓取失败: {e} (source={e.source}, recoverable={e.recoverable})")
        except Exception as e:
            err = categorize_cli_error(e, "host-events")
            oc.errors.append(err)
            oc.log.append(f"  ❌ 主机电源/重启/崩溃事件抓取失败: {err} (source={err.source}, recoverable={err.recoverable})")
        return oc


# ---------------------------------------------------------------- 注册表

def build_sources(args) -> List[DataSource]:
    """注册表：按参数裁剪出本次要跑的插件列表（新增数据源在这里追加一行）。

    并行批次 = order < 40 的插件（服务端/RPA/ops，互相独立）；
    串行批次 = order >= 40 的主机侧插件（可选，依赖用户提供的参数）。
    """
    plugins: List[DataSource] = [
        ServerLogSource(),
        RPALogSource(),
        OpsSource(),
    ]
    if getattr(args, 'host_bundle', None):
        plugins.append(HostBundleSource())
    if getattr(args, 'host_events_equipment', None) or getattr(args, 'host_events_desktop', None):
        plugins.append(HostEventsSource())
    return sorted(plugins, key=lambda p: p.order)
