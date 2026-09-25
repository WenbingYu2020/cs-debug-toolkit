#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
host_events_query.py — 第④源「目标设备系统 电源 / 重启 / 崩溃 事件」抓取

用途:
  给定目标设备（equipment_id 平台设备ID 或 desktop_id ECD 云电脑ID）+ 时间窗口，
  抓取该设备主机的 电源(睡眠/休眠/断流) / 重启(开机/关机/异常关机) / 崩溃(应用崩溃/RPA进程重启)
  事件，产出与 cross_analysis.py --host-bundle 兼容的文本 / host 记录。

两条取数通道（优先级从高到低）:
  1. ECD 远程通道（实锤）: 目标设备是无影云电脑且配置了 ~/.csdbg/ecd.json 时，
     经 lib/host-runner.js (RunCommand) 远程执行 collect_host_events.ps1，
     按 EventID 分类: 42/107/1/12/13/27/32 → power；1074/1076/6005/6006/6008/41/6013 → restart；
     1000/1002/1001 → crash；4201/4202 → net。
  2. SLS 心跳重建（兜底，常态可用）: 用 rpa_log_query.py 按 equipment_id 拉
     robot-health-report 心跳时间线，从 uptime_seconds / rpa_status / client_status /
     app_version 变化重建事件:
       - uptime 骤降 → 系统重启（可反推开机时刻）
       - 心跳断流 ≥ min_gap 且 uptime 未重置 → 睡眠/休眠/关机（进程挂起）
       - 同一次开机内 app_version 变化 → RPA 进程重启/升级（疑似崩溃）
       - rpa_status/client_status 切换 → 上线/下线/挂起

用法:
  # 设备ID + 时间窗（SLS 兜底）
  python host_events_query.py --equipment-id abcdef0123456789abcdef0123456789 \
      --start "2026-09-21T00:00:00" --end "2026-09-22T23:59:59" [--save host_events.txt]

  # 云电脑 + 时间窗（ECD 实锤优先，可叠加设备ID做 SLS 面补充）
  python host_events_query.py --desktop-id ecd-xxxxxxxxx \
      --start "2026-09-21T00:00:00" --end "2026-09-22T23:59:59" [--save host_events.txt]

  # 环境自检
  python host_events_query.py --check

输出:
  stdout 时间线（YYYY-MM-DD HH:MM:SS [kind] [LEVEL] 事件），--save 落盘纯文本，
  可直接喂 cross_analysis.py --host-bundle；cross_analysis.py --host-events-* 内嵌调用。
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# BetterYeah 业务统一北京时间(UTC+8)
CST = timezone(timedelta(hours=8))

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

from rpa_log_query import RPALogQuery  # noqa: E402

HEARTBEAT_KW = 'robot-health-report'
MIN_GAP_DEFAULT = 300            # 心跳每 ~30s 一条；断流 ≥ 5min 视为事件
MEM_DROP_SYSTEM_REBOOT = 15      # 重启瞬间内存骤降 ≥15pp → 倾向系统重启

# 主机事件日志 EventID → 类别（与 collect_host_events.ps1 / host-events.ps1 签名一致）
EVENT_KINDS = {
    42: 'power', 107: 'power', 1: 'power', 12: 'power', 13: 'power', 27: 'power', 32: 'power',
    1074: 'restart', 1076: 'restart', 6005: 'restart', 6006: 'restart', 6008: 'restart',
    41: 'restart', 6013: 'restart',
    1000: 'crash', 1002: 'crash', 1001: 'crash',
    4201: 'net', 4202: 'net',
}
EVENT_LABEL = {'power': '电源/睡眠', 'restart': '重启/关机', 'crash': '崩溃', 'net': '网络', 'other': '其他'}

_LEVEL_MAP = {
    '错误': 'ERROR', '严重': 'CRITICAL', '警告': 'WARNING', '信息': 'INFO', '详细': 'VERBOSE',
    'error': 'ERROR', 'critical': 'CRITICAL', 'warning': 'WARNING',
    'information': 'INFO', 'verbose': 'VERBOSE',
}
_LINE_TS = re.compile(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})[ T](\d{1,2}:\d{2}(?::\d{2})?)')


def _fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=CST).strftime('%Y-%m-%d %H:%M:%S') if ts else ''


def _host_level(raw: str) -> str:
    r = (raw or '').strip()
    return _LEVEL_MAP.get(r, _LEVEL_MAP.get(r.lower(), r.upper()[:12]))


def _parse_ts(m) -> float:
    for sep in ('/', '-'):
        try:
            dt = datetime.strptime(m.group(1).replace('/', sep) + ' ' + m.group(2),
                                   f'%Y{sep}%m{sep}%d ' +
                                   ('%H:%M:%S' if m.group(2).count(':') == 2 else '%H:%M'))
            return dt.timestamp()
        except ValueError:
            continue
    return 0.0


def _mk_rec(kind: str, ts: float, message: str, level: str,
            host: str = '', source: str = 'sls') -> Dict:
    # confidence: ECD 事件日志=实锤(high)，SLS 心跳重建=推断(medium)，供论证时区分可信度
    return {'source': 'host', 'host_kind': kind, 'host': host,
            'time': _fmt(ts), 'time_tz': 'Asia/Shanghai', 'ts': ts or 0, 'level': level,
            'message': message, 'ids': {}, 'host_source': source,
            'confidence': 'high' if source == 'ecd' else 'medium'}


def _parse_data(r: Dict) -> Dict:
    """心跳 data 字段是嵌套 JSON：{"data": {"rpa_status":..., "uptime_seconds":...}}。
    取内层 dict；兼容平铺结构。"""
    d = r.get('data') or ''
    if not isinstance(d, str) or not d.startswith('{'):
        return {}
    try:
        o = json.loads(d)
    except Exception:
        return {}
    if isinstance(o, dict) and isinstance(o.get('data'), dict):
        return o['data']
    return o if isinstance(o, dict) else {}


def resolve_identity(recs: List[Dict]) -> Dict:
    """从原始日志里还原设备身份（hostname / desktop_name / desktop_id / 出口IP）"""
    for r in recs:
        if r.get('hostname') or r.get('desktop_name'):
            return {'hostname': r.get('hostname') or '',
                    'desktop_name': r.get('desktop_name') or '',
                    'desktop_id': r.get('desktop_id') or '',
                    'ip': r.get('__tag__:__client_ip__') or ''}
    return {}


def _state_intervals(recs: List[Dict]) -> List[Tuple[str, float, Optional[float]]]:
    """心跳状态区间: (rpa/client 状态, 起始ts, 结束ts或None)"""
    hb = [r for r in recs if HEARTBEAT_KW in (r.get('message') or '')]
    hb.sort(key=lambda r: r.get('__time__', 0) or 0)
    out, prev = [], None
    for r in hb:
        ts = int(r.get('__time__', 0) or 0)
        d = _parse_data(r)
        st = f"{d.get('rpa_status') or '?'}/{d.get('client_status') or '?'}"
        if prev is None:
            prev = (st, ts)
        elif st != prev[0]:
            out.append((prev[0], prev[1], ts))
            prev = (st, ts)
    if prev:
        out.append((prev[0], prev[1], None))
    return out


def rebuild_sls_events(recs: List[Dict], min_gap: int = MIN_GAP_DEFAULT,
                       window_start: float = 0, window_end: float = 0) -> List[Dict]:
    """由 robot-health-report 心跳时间线重建 电源/重启/崩溃 事件（SLS 面，推断性质）。

    判定规则:
      · uptime_seconds 相对上条**任何回退** → 重启（RPA 进程或宿主重启）
      · 断流 ≥ min_gap：
          - 恢复时 uptime 回退 → 重启（重启发生在断流期间，取恢复时刻-uptime 为开机点）
          - 恢复时 uptime 未回退 → 睡眠/休眠/挂起或关机
      · 重启瞬间内存骤降（≥15pp）→ 倾向系统重启；内存基本不变 → 倾向 RPA 进程重启
      · 同一次开机内 app_version 变化 → 崩溃/升级
      · 300s 内连续两次重启 → 疑似崩溃循环
      · rpa_status/client_status 切换 → 上线/下线/挂起（state）
    """
    hb = [r for r in recs if HEARTBEAT_KW in (r.get('message') or '')]
    hb.sort(key=lambda r: r.get('__time__', 0) or 0)
    events: List[Dict] = []
    prev = None  # (ts, uptime, rpa_status, client_status, app_version, mem)
    last_restart_ts: Optional[float] = None
    for r in hb:
        ts = int(r.get('__time__', 0) or 0)
        if not ts:
            continue
        d = _parse_data(r)
        uptime = d.get('uptime_seconds')
        rpa_st = d.get('rpa_status') or ''
        cli_st = d.get('client_status') or ''
        ver = str(r.get('app_version') or '')
        mem = d.get('memory_percent')
        if prev is not None:
            pts, pu, prpa, pcli, pver, pmem = prev
            gap = ts - pts
            uptime_reset = (uptime is not None and pu is not None and uptime < pu)
            if gap >= min_gap:
                if uptime_reset:
                    boot = ts - uptime
                    mem_note = _reboot_mem_note(pmem, mem)
                    events.append(_mk_rec(
                        'restart', boot,
                        f"[SLS推断] 重启：心跳断流 {gap}s（{_fmt(pts)} → {_fmt(ts)}），"
                        f"恢复时 uptime 重置 {pu}s → {uptime}s（约 {_fmt(boot)} 重启）{mem_note}",
                        'INFO'))
                else:
                    events.append(_mk_rec(
                        'power', pts,
                        f"[SLS推断] 心跳断流 {gap}s（{_fmt(pts)} → {_fmt(ts)}），uptime 未回退 "
                        "→ 睡眠/休眠或关机（进程挂起）",
                        'WARNING'))
            elif uptime_reset:
                boot = ts - uptime
                events.append(_mk_rec(
                    'restart', boot,
                    f"[SLS推断] 重启 @ {_fmt(boot)}：uptime 回退 {pu}s → {uptime}s"
                    f"{_reboot_mem_note(pmem, mem)}", 'INFO'))
            # 快速连续重启 → 崩溃循环
            if uptime_reset and last_restart_ts is not None and ts - last_restart_ts <= 300:
                events.append(_mk_rec(
                    'crash', ts,
                    f"[SLS推断] 疑似崩溃循环：{int(ts - last_restart_ts)}s 内再次重启 "
                    f"（uptime 回退 {pu}s → {uptime}s）", 'ERROR'))
            if uptime_reset:
                last_restart_ts = ts
            if ver and pver and ver != pver:
                events.append(_mk_rec(
                    'crash', ts,
                    f"[SLS推断] RPA 进程重启/升级：app_version {pver} → {ver}"
                    "（同一次开机内，疑似崩溃或升级）", 'ERROR'))
            if (rpa_st or cli_st) and (rpa_st, cli_st) != (prpa, pcli):
                events.append(_mk_rec(
                    'state', ts,
                    f"[SLS推断] RPA 状态切换 {prpa}/{pcli} → {rpa_st}/{cli_st}", 'INFO'))
        prev = (ts, uptime, rpa_st, cli_st, ver, mem)

    if not hb:
        events.append(_mk_rec(
            'power', window_start or 0,
            '[SLS推断] 窗口内无该设备心跳（robot-health-report）→ 设备未运行或通道无上报',
            'WARNING'))
    return events


def _reboot_mem_note(pmem, mem) -> str:
    """用重启前后内存变化区分 系统重启 / RPA 进程重启。"""
    if pmem is None or mem is None:
        return ''
    try:
        drop = float(pmem) - float(mem)
    except (TypeError, ValueError):
        return ''
    if drop >= 15:
        return f"（内存 {pmem}% → {mem}%，骤降 → 倾向系统重启）"
    if drop <= -5:
        return f"（内存 {pmem}% → {mem}%，不降反升，倾向 RPA 进程重启）"
    return f"（内存 {pmem}% → {mem}%，基本不变，倾向 RPA 进程重启）"


# ------------------------------------------------------------ ECD 通道

def _find_host_runner() -> Optional[Path]:
    env = os.environ.get('CSDBG_HOST_RUNNER')
    cands = [Path(env)] if env else []
    cands += [SCRIPT_DIR.parent / 'lib' / 'host-runner.js',      # npm 形态
              SCRIPT_DIR.parent / 'cli' / 'lib' / 'host-runner.js']  # 源码形态
    for c in cands:
        if c.exists():
            return c
    return None


def _ecd_config() -> Tuple[Optional[Dict], str]:
    """ECD 配置候选顺序: 环境变量 CSDBG_ECD_CONFIG > ~/.csdbg/ecd.json（CLI 形态）
    > scripts/ecd.json（zip 形态 setup.ps1 生成的位置）"""
    cands = [
        os.environ.get('CSDBG_ECD_CONFIG'),
        str(Path.home() / '.csdbg' / 'ecd.json'),
        str(SCRIPT_DIR / 'ecd.json'),
    ]
    p = next((Path(c) for c in cands if c and Path(c).exists()), None)
    if p is None:
        return None, f'ECD 配置不存在（已找: {"、".join(c for c in cands if c)}）——创建并填 access_key_id/access_key_secret/region'
    try:
        cfg = json.loads(p.read_text(encoding='utf-8-sig'))
    except Exception as e:
        return None, f'ECD 配置解析失败: {e}'
    for k in ('access_key_id', 'access_key_secret', 'region'):
        v = cfg.get(k)
        if not v or str(v).startswith(('YOUR_', '<', 'xxx')):
            return None, f'ECD 配置字段缺失或仍是占位符: {k}'
    return cfg, ''


def _find_node() -> Optional[str]:
    env = os.environ.get('CSDBG_NODE')
    if env:
        return env
    import shutil
    return shutil.which('node') or shutil.which('node.exe')


def run_ecd_desktop(desktop_id: str, script: Optional[Path] = None,
                    timeout: int = 120) -> Tuple[Optional[str], str]:
    """经 lib/host-runner.js（RunCommand）在 ECD 云电脑执行采集脚本。返回 (stdout文本, 错误)。"""
    runner = _find_host_runner()
    if runner is None:
        return None, '未找到 lib/host-runner.js（npm 形态才有；zip 形态请用 csdbg host-pull 或手动拷贝脚本）'
    cfg, err = _ecd_config()
    if cfg is None:
        return None, err
    node = _find_node()
    if not node:
        return None, '未找到 node 可执行文件（ECD 通道需要 node + @alicloud/ecd20200930）'
    script = script or (SCRIPT_DIR / 'collect_host_events.ps1')
    if not script.exists():
        return None, f'采集脚本不存在: {script}'
    cmd = [node, str(runner), desktop_id, str(script), str(timeout)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding='utf-8', errors='replace',
                              timeout=timeout + 90, cwd=str(SCRIPT_DIR))
    except subprocess.TimeoutExpired:
        return None, f'ECD 执行超时（>{timeout + 90}s）'
    except Exception as e:
        return None, f'ECD 执行失败: {e}'
    if proc.returncode not in (0, None) and 'Success' not in (proc.stderr or ''):
        return None, (proc.stderr or proc.stdout or '').strip()[-400:]
    return proc.stdout or '', ''


def parse_ecd_text(text: str, host: str = '') -> List[Dict]:
    """解析 collect_host_events.ps1（CSV 行）与 host-events.ps1（ID= 行）的远程输出"""
    out: List[Dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        eid, msg, lvl, ts = None, line, '', 0.0
        if line.startswith('"'):
            try:
                row = next(csv.reader([line]))
            except Exception:
                row = []
            if len(row) >= 4:
                tm = _LINE_TS.search(row[0])
                if tm:
                    ts = _parse_ts(tm)
                    eid = row[2]
                    lvl = _host_level(row[1])
                    msg = f"{row[3]} {row[4] if len(row) > 4 else ''}".strip()[:200]
        else:
            tm = _LINE_TS.search(line)
            m = re.search(r'ID=(\d+)', line)
            if tm and m:
                ts = _parse_ts(tm)
                eid = m.group(1)
                msg = line[:200]
        if not ts or eid is None:
            continue
        kind = EVENT_KINDS.get(int(eid), 'other')
        out.append(_mk_rec(
            kind, ts,
            f"[主机事件日志] {EVENT_LABEL.get(kind, '其他')} ID={eid} {msg}",
            lvl or ('WARNING' if kind in ('crash', 'net') else 'INFO'), host, 'ecd'))
    out.sort(key=lambda r: r.get('ts') or 0)
    return out


# ------------------------------------------------------------ 主入口

def pull_host_events(equipment_id: str = '', desktop_id: str = '',
                     start: Optional[str] = None, end: Optional[str] = None,
                     channel: Optional[str] = None, min_gap: int = MIN_GAP_DEFAULT,
                     limit: int = 5000, ecd_timeout: int = 120,
                     ecd_script: Optional[Path] = None,
                     quiet: bool = False) -> Tuple[List[Dict], Dict]:
    """第④源事件抓取总入口。返回 (记录列表, meta)。
    meta: host / summary / ecd_note / device / source_labels"""
    now = datetime.now(tz=CST)
    start_dt = datetime.fromisoformat(start) if start else (now - timedelta(hours=48))
    start_dt = start_dt if start_dt.tzinfo else start_dt.replace(tzinfo=CST)
    end_dt = datetime.fromisoformat(end) if end else now
    end_dt = end_dt if end_dt.tzinfo else end_dt.replace(tzinfo=CST)
    recs: List[Dict] = []
    raw_all: List[Dict] = []
    source_labels: List[str] = []
    ecd_note = ''

    # 1) ECD 远程通道（实锤）
    if desktop_id:
        txt, err = run_ecd_desktop(desktop_id, ecd_script, ecd_timeout)
        if txt is None:
            ecd_note = f'ECD 通道不可用：{err}'
            if not quiet:
                print(f'  ⚠ {ecd_note}')
        else:
            recs = parse_ecd_text(txt, host=f'ecd-{desktop_id}')
            source_labels.append('ECD 主机事件日志')
            if not quiet:
                print(f'  ✅ ECD 拉起 {len(recs)} 条主机事件日志（{desktop_id}）')

    # 2) SLS 心跳重建（兜底/常态）
    if equipment_id:
        try:
            rq = RPALogQuery()
            channels = [channel] if channel else list(rq.config['channels'].keys())
            for ch in channels:
                try:
                    raw_all += rq.query(
                        channel=ch,
                        start_time=start_dt.isoformat(timespec='seconds'),
                        end_time=end_dt.isoformat(timespec='seconds'),
                        equipment_id=equipment_id, query_text=HEARTBEAT_KW,
                        limit=limit, quiet=True)
                except Exception as e:
                    if not quiet:
                        print(f'  ❌ 渠道 {ch} 查询失败: {e}')
            raw_all.sort(key=lambda r: r.get('__time__', 0) or 0)
            ev = rebuild_sls_events(raw_all, min_gap=min_gap,
                                    window_start=start_dt.timestamp(),
                                    window_end=end_dt.timestamp())
            recs += ev
            source_labels.append('SLS 心跳重建')
            if not quiet:
                print(f'  ✅ SLS 心跳重建 {len(ev)} 条事件（原始心跳 {len(raw_all)} 条）')
        except Exception as e:
            if not quiet:
                print(f'  ❌ SLS 心跳重建失败: {e}')

    # 去重（同一时刻同一事件只留一条）
    seen, dedup = set(), []
    for r in sorted(recs, key=lambda r: r.get('ts') or 0):
        key = (r.get('ts'), r.get('host_kind'), r.get('message'))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)

    identity = resolve_identity(raw_all) or resolve_identity(dedup)
    host = identity.get('hostname') or (f'ecd-{desktop_id}' if desktop_id else '')
    if identity:
        host = identity.get('hostname') or host

    summary = []
    summary.append(f'host: {host or "未知"}')
    summary.append(f'equipment_id: {equipment_id or "-"}  desktop_id: {desktop_id or "-"}')
    summary.append(f'device: {json.dumps(identity, ensure_ascii=False)}')
    summary.append(f'window: {start_dt.strftime("%Y-%m-%d %H:%M:%S")} ~ {end_dt.strftime("%Y-%m-%d %H:%M:%S")}')
    summary.append(f'source: {" + ".join(source_labels) or "无"}')
    if ecd_note:
        summary.append(f'ecd_note: {ecd_note}')
    if raw_all:
        summary.append('state_intervals:')
        for st, s0, s1 in _state_intervals(raw_all):
            summary.append(f'  {st}  {_fmt(s0)} → {_fmt(s1) if s1 else "(窗口内持续)"}')
    kind_stat = Counter(r.get('host_kind') for r in dedup)
    summary.append('event_counts: ' + ' '.join(f'{k}={c}' for k, c in kind_stat.most_common()))

    meta = {'host': host, 'summary': '\n'.join(summary), 'ecd_note': ecd_note,
            'device': identity, 'count': len(dedup),
            'source_labels': source_labels}
    return dedup, meta


def main():
    p = argparse.ArgumentParser(
        description='第④源：目标设备 电源/重启/崩溃 事件抓取（ECD 远程实锤优先，SLS 心跳重建兜底）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('用法:')[1].split('输出:')[0] if '用法:' in __doc__ else '')
    p.add_argument('equipment', nargs='?',
                   help='设备 ID（位置参数，等价 --equipment-id；二选一即可）')
    p.add_argument('--equipment-id', help='设备 ID（平台侧 equipment_id，SLS 心跳重建用）')
    p.add_argument('--desktop-id', help='ECD 云电脑 desktopId（RunCommand 实锤）')
    # 渠道名不设硬编码 choices：以 channels.json 配置为准（rpa_log_query.query() 内有运行时校验）
    p.add_argument('--channel', help='RPA 渠道（缺省全渠道）')
    p.add_argument('--start', help='开始时间 ISO（缺省最近 48h）')
    p.add_argument('--end', help='结束时间 ISO（缺省现在）')
    p.add_argument('--min-gap', type=int, default=MIN_GAP_DEFAULT,
                   help='心跳断流阈值秒（默认 300）')
    p.add_argument('--limit', type=int, default=5000, help='单渠道心跳条数上限（默认 5000）')
    p.add_argument('--save', help='输出文本文件路径（可直接喂 cross_analysis --host-bundle）')
    p.add_argument('--check', action='store_true', help='环境自检（SLS 连通 / ECD 配置）')
    p.add_argument('--quiet', action='store_true', help='只输出事件行')
    args = p.parse_args()

    if args.check:
        print('=== host_events_query 环境自检 ===')
        try:
            RPALogQuery()
            print('  ✅ SLS 配置可读（RPA 源）')
        except Exception as e:
            print(f'  ❌ SLS 配置不可用: {e}')
        runner = _find_host_runner()
        print(f"  {'✅' if runner else '⚠'} host-runner.js: {runner or '未找到（npm 形态才有 ECD 通道）'}")
        cfg, err = _ecd_config()
        print(f"  {'✅' if cfg else '⚠'} ECD 配置: {err or '已就位'}")
        print(f"  {'✅' if _find_node() else '⚠'} node: {_find_node() or '未找到'}")
        return 0

    if args.equipment and not args.equipment_id:
        args.equipment_id = args.equipment
    if not args.equipment_id and not args.desktop_id:
        print('❌ 至少提供 设备ID（位置参数或 --equipment-id）或 --desktop-id 之一')
        p.print_help()
        return 1

    recs, meta = pull_host_events(
        equipment_id=args.equipment_id, desktop_id=args.desktop_id,
        start=args.start, end=args.end, channel=args.channel,
        min_gap=args.min_gap, limit=args.limit, quiet=args.quiet)

    if not args.quiet:
        print('')
        print('=== 设备电源/重启/崩溃事件时间线 ===')
        print(f"# {meta['summary']}".replace('\n', '\n# '))
        print('')
    for r in recs:
        print(f"{r['time']} [{r['host_kind']}] [{r.get('level','')}] {r['message']}")
    if not args.quiet:
        print(f"\n共 {len(recs)} 条事件")

    if args.save:
        Path(args.save).write_text(
            ''.join(f"{r['time']} [{r['host_kind']}] {r['message']}\n" for r in recs),
            encoding='utf-8')
        print(f"\n✅ 已保存: {args.save}（可直接喂 cross_analysis --host-bundle）")
    return 0


if __name__ == '__main__':
    sys.exit(main())
