#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fault_signatures.py — 故障签名知识库加载与匹配（P4-11）

知识库: templates/fault_signatures.json（随包分发，通用化）；
本地可复制到 ~/.csdbg/fault_signatures.json 增补（同 id 覆盖包内条目）。

匹配语义（evidence_pattern 每源的规则）:
  regex_all  —— 记录文本(JSON)需同时命中的正则
  regex_any  —— 命中其一即可
  min_count  —— 命中条数下限（有正则时默认 1）
  max_count  —— 命中条数上限（0 = 该源必须无记录）
  evidence_pattern 为空的条目 = 参考条目，不参与自动匹配。

CLI:
  python fault_signatures.py --list [--json] [--id <id>]   # 列出知识库
  python fault_signatures.py --check                       # 校验（可解析/id 唯一/正则可编译）
  python fault_signatures.py --match-dir <证据包目录>       # 对已有证据包跑匹配（复检用）
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None


def _kb_candidates() -> List[Path]:
    """知识库候选路径（后者覆盖前者同 id 条目）：包内 templates → 用户本地 ~/.csdbg。"""
    env = os.environ.get('CSDBG_SIGNATURES')
    cands: List[Path] = []
    if env:
        cands.append(Path(env))
    # 包内（源码/zip/npm 三形态 scripts 与 templates 均为兄弟目录）
    cands.append(SCRIPT_DIR.parent / 'templates' / 'fault_signatures.json')
    cands.append(SCRIPT_DIR / 'fault_signatures.json')          # 兜底
    # 用户本地增补
    home = Path(os.environ.get('CSDBG_HOME') or (Path.home() / '.csdbg'))
    cands.append(home / 'fault_signatures.json')
    return cands


def load_signatures(path: str = None) -> List[Dict]:
    """加载知识库并合并（包内 + 用户本地，同 id 后者覆盖）。解析失败返回空列表。"""
    merged: Dict[str, Dict] = {}
    paths = [Path(path)] if path else _kb_candidates()
    for p in paths:
        if not p.exists():
            continue
        try:
            doc = json.loads(p.read_text(encoding='utf-8-sig'))
        except Exception:
            continue
        sigs = doc.get('signatures') if isinstance(doc, dict) else doc
        if not isinstance(sigs, list):
            continue
        for sig in sigs:
            if isinstance(sig, dict) and sig.get('id'):
                merged[sig['id']] = sig
    return list(merged.values())


def _source_records(key: str, sources: Dict[str, List[Dict]]) -> List[Dict]:
    """'rpa' 聚合全部 rpa:<channel>；其余按源名取值。"""
    if key == 'rpa':
        return [r for k, v in (sources or {}).items() if k.startswith('rpa:') for r in v]
    return list((sources or {}).get(key, []))


def _blobs(records: List[Dict]) -> List[str]:
    return [json.dumps(r, ensure_ascii=False) for r in records]


def _check_rule(rule: Dict, blob_list: List[str]):
    """返回 (是否通过, 命中条数)。"""
    rx_all = [re.compile(p, re.I) for p in rule.get('regex_all', [])]
    rx_any = [re.compile(p, re.I) for p in rule.get('regex_any', [])]
    if rx_all or rx_any:
        n = sum(1 for b in blob_list
                if all(rx.search(b) for rx in rx_all)
                and (not rx_any or any(rx.search(b) for rx in rx_any)))
    else:
        n = len(blob_list)
    lo = rule.get('min_count', 1 if (rx_all or rx_any) else 0)
    hi = rule.get('max_count')
    ok = n >= lo and (hi is None or n <= hi)
    return ok, n


def match_signatures(sources: Dict[str, List[Dict]], kb: List[Dict] = None) -> List[Dict]:
    """对四方 sources 跑知识库匹配，返回命中列表（保持 KB 顺序）。

    返回项: {id, type, name, severity_hint, matched: {源: 条数}, conclusion_template, signature}
    """
    kb = kb if kb is not None else load_signatures()
    blob_cache: Dict[str, List[str]] = {}
    hits: List[Dict] = []
    for sig in kb:
        pattern = sig.get('evidence_pattern') or {}
        if not pattern:
            continue                      # 参考条目：不自动匹配
        matched: Dict[str, int] = {}
        ok = True
        for key, rule in pattern.items():
            if key not in blob_cache:
                blob_cache[key] = _blobs(_source_records(key, sources))
            passed, n = _check_rule(rule, blob_cache[key])
            if not passed:
                ok = False
                break
            matched[key] = n
        if ok:
            hits.append({
                'id': sig.get('id', ''),
                'type': sig.get('type', ''),
                'name': sig.get('name', ''),
                'severity_hint': sig.get('severity_hint', ''),
                'matched': matched,
                'signature': sig.get('signature', []),
                'conclusion_template': sig.get('conclusion_template', ''),
            })
    return hits


def check_kb(kb: List[Dict]) -> List[str]:
    """校验知识库：id 唯一、正则可编译。返回问题列表（空 = 通过）。"""
    problems: List[str] = []
    seen = set()
    for sig in kb:
        sid = sig.get('id')
        if not sid:
            problems.append('存在缺少 id 的条目')
            continue
        if sid in seen:
            problems.append(f'id 重复: {sid}')
        seen.add(sid)
        for key, rule in (sig.get('evidence_pattern') or {}).items():
            for field in ('regex_all', 'regex_any'):
                for pat in rule.get(field, []) or []:
                    try:
                        re.compile(pat)
                    except re.error as e:
                        problems.append(f'{sid}.{key}.{field} 正则非法: {pat} ({e})')
    return problems


def _load_evidence_dir(d: Path) -> Dict[str, List[Dict]]:
    """从证据包目录读回四方 sources（server.json / rpa_*.json / ops.json / host.json）。"""
    sources: Dict[str, List[Dict]] = {}
    for f in sorted(d.glob('*.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8-sig'))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        if f.name == 'server.json':
            sources['server'] = data
        elif f.name.startswith('rpa_'):
            sources[f'rpa:{f.stem[4:]}'] = data
        elif f.name == 'ops.json':
            sources['ops'] = data
        elif f.name == 'host.json':
            sources['host'] = data
    return sources


def main() -> int:
    ap = argparse.ArgumentParser(description='故障签名知识库（列出/校验/对证据包复检匹配）')
    ap.add_argument('--list', action='store_true', help='列出知识库条目')
    ap.add_argument('--json', action='store_true', help='与 --list 配合：输出 JSON')
    ap.add_argument('--id', help='只看指定条目')
    ap.add_argument('--check', action='store_true', help='校验知识库（id/正则）')
    ap.add_argument('--match-dir', help='对已有证据包目录跑匹配（复检）')
    ap.add_argument('--config', help='指定知识库文件路径（默认：包内 templates + ~/.csdbg 合并）')
    a = ap.parse_args()

    kb = load_signatures(a.config)
    if a.check:
        problems = check_kb(kb)
        if problems:
            print(f'❌ 知识库校验未通过（{len(problems)} 项）：')
            for p in problems:
                print(f'  - {p}')
            return 1
        auto = sum(1 for s in kb if s.get('evidence_pattern'))
        print(f'✅ 知识库校验通过：{len(kb)} 条（其中 {auto} 条参与自动匹配，'
              f'{len(kb) - auto} 条为参考条目）')
        return 0

    if a.match_dir:
        d = Path(a.match_dir)
        if not d.is_dir():
            print(f'❌ 目录不存在: {d}')
            return 1
        sources = _load_evidence_dir(d)
        if not sources:
            print(f'⚠ 目录内未找到 server.json / rpa_*.json / ops.json / host.json：{d}')
            return 1
        hits = match_signatures(sources, kb)
        print(f'▶ 证据包: {d}')
        print(f'  已载入源: ' + ', '.join(f'{k}={len(v)}条' for k, v in sources.items()))
        if not hits:
            print('  未命中任何签名（可能未覆盖，或为新型故障）')
            return 0
        print(f'  命中 {len(hits)} 条候选签名：')
        for h in hits:
            t = f"[{h['type']}] " if h['type'] else ''
            match_str = ', '.join(f"{k}×{v}" for k, v in h['matched'].items())
            print(f"    - {t}{h['name']}（命中: {match_str}）")
            if h['conclusion_template']:
                print(f"      结论模板: {h['conclusion_template']}")
        return 0

    # 默认/--list
    sigs = kb
    if a.id:
        sigs = [s for s in sigs if s.get('id') == a.id]
        if not sigs:
            print(f'❌ 未找到条目: {a.id}')
            return 1
    if a.json:
        print(json.dumps(sigs, ensure_ascii=False, indent=2))
        return 0
    print(f'故障签名知识库：{len(sigs)} 条')
    for s in sigs:
        pat = s.get('evidence_pattern') or {}
        tag = '自动' if pat else '参考'
        t = f"[{s.get('type')}] " if s.get('type') else ''
        print(f"  - [{tag}] {t}{s.get('name')}  ({s.get('id')})")
    print('\n提示: --check 校验 / --match-dir <证据包目录> 复检匹配')
    return 0


if __name__ == '__main__':
    sys.exit(main())
