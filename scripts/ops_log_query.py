#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ops 运维日志查询工具 - 通过本地安装的 @bty/customer-service-cli (cs-cli)
拉取运维操作记录 (ops-record)，作为交叉分析的第三个数据源。

数据链路: 本脚本 → cs-cli ops-record list/get → 服务端运维记录库。
说明: ops-record list 无服务端时间过滤，本脚本自动翻页并按 created_at 客户端过滤。

示例:
  # 验证 cs-cli 认证
  python3 ops_log_query.py --check

  # 拉取最近 N 条运维记录
  python3 ops_log_query.py --limit 50

  # 按时间窗口 + Agent + 关键词过滤
  python3 ops_log_query.py --start 2026-09-18T00:00:00 --end 2026-09-18T23:59:59 \
      --agent <agent_id> --keyword "FAQ"

  # 单条详情
  python3 ops_log_query.py --record-id <record_id>

  # 保存 JSON（供 cross_analysis.py 使用）
  python3 ops_log_query.py --start ... --end ... --output ../temp/ops.json
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

# BetterYeah 业务统一北京时间(UTC+8)：naive 时间按北京时间解释，
# 保证时间窗过滤与 created_at 比较两侧时区一致（避免 aware/naive 混比报错）。
CST = timezone(timedelta(hours=8))


def _as_cst(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=CST)
from pathlib import Path
from typing import Dict, List, Optional

sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

PAGE_SIZE = 100
MAX_PAGES = 50  # 安全上限，防止无限翻页


def _cs_cli_path() -> str:
    """cs-cli 解析顺序: 环境变量 CS_CLI > PATH（Windows 下命中 cs-cli.cmd）。"""
    return os.environ.get('CS_CLI') or shutil.which('cs-cli') or 'cs-cli'


def _run_cs_cli(args: List[str]) -> Optional[Dict]:
    """执行 cs-cli 子命令并解析 JSON（容忍尾部版本提示噪音）。"""
    try:
        proc = subprocess.run(
            [_cs_cli_path()] + args, capture_output=True, text=True,
            encoding='utf-8', timeout=120,
        )
    except FileNotFoundError:
        print("❌ 未找到 cs-cli，请先: npm install -g @bty/customer-service-cli")
        return None
    except subprocess.TimeoutExpired:
        print("❌ cs-cli 执行超时")
        return None
    out = (proc.stdout or '').strip()
    if not out:
        print(f"❌ cs-cli 无输出 (exit={proc.returncode}): {proc.stderr[:200]}")
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(out)
        return data
    except json.JSONDecodeError:
        print(f"❌ cs-cli 输出解析失败: {out[:200]}")
        return None


def _parse_time(s: str) -> datetime:
    return _as_cst(datetime.fromisoformat(s))


def check() -> bool:
    data = _run_cs_cli(['auth', 'whoami'])
    if data and data.get('success'):
        u = data.get('data', {})
        print("✅ cs-cli 认证正常")
        print(f"  用户: {u.get('name') or u.get('username') or u.get('phone') or json.dumps(u, ensure_ascii=False)[:120]}")
        return True
    print(f"❌ cs-cli 未登录或异常，请运行 cs-cli auth login")
    return False


def list_records(
    start: Optional[str] = None,
    end: Optional[str] = None,
    workspace: Optional[str] = None,
    agent: Optional[str] = None,
    operator: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 200,
    quiet: bool = False,
) -> List[Dict]:
    """翻页拉取 ops-record，客户端过滤，返回规范化记录（按 created_at 升序）。"""
    cli_args = ['ops-record', 'list', '--page-size', str(PAGE_SIZE)]
    if workspace:
        cli_args += ['--workspace-id', workspace]
    if agent:
        cli_args += ['--agent', agent]

    start_dt = _parse_time(start) if start else None
    end_dt = _parse_time(end) if end else None
    kw_pat = re.compile(re.escape(keyword), re.I) if keyword else None

    records: List[Dict] = []
    seen_ids = set()
    for page in range(1, MAX_PAGES + 1):
        data = _run_cs_cli(cli_args + ['--page', str(page)])
        if not data or not data.get('success'):
            if page == 1:
                print(f"❌ ops-record list 失败: {json.dumps(data, ensure_ascii=False)[:200] if data else '无响应'}")
            break
        batch = (data.get('data') or {}).get('records') or []
        if not batch:
            break
        new = [r for r in batch if r.get('record_id') not in seen_ids]
        if len(new) < len(batch):  # 已到尾页（重复数据）
            records.extend(new)
            break
        records.extend(new)
        if len(batch) < PAGE_SIZE:
            break
        # 服务端按 created_at 降序返回：整页都已早于 start 时提前终止翻页
        if start_dt:
            try:
                oldest = _as_cst(datetime.fromisoformat(batch[-1].get('created_at')))
            except (ValueError, TypeError):
                oldest = None
            if oldest and oldest < start_dt:
                break

    out: List[Dict] = []
    for r in records:
        created = r.get('created_at') or ''
        try:
            dt = _as_cst(datetime.fromisoformat(created)) if created else None
        except ValueError:
            dt = None
        if start_dt and (not dt or dt < start_dt):
            continue
        if end_dt and (not dt or dt > end_dt):
            continue
        if operator and operator not in (r.get('operator_name') or ''):
            continue
        if kw_pat and not (kw_pat.search(r.get('remark') or '') or kw_pat.search(r.get('path') or '')):
            continue
        out.append({
            'source': 'ops',
            'record_id': r.get('record_id'),
            'time': created,
            'ts': dt.timestamp() if dt else 0,
            'workspace_id': r.get('workspace_id'),
            'agent_id': r.get('agent_id'),
            'operator': r.get('operator_name'),
            'path': r.get('path'),
            'remark': r.get('remark'),
            'created_at': created,
            'updated_at': r.get('updated_at'),
        })
        if len(out) >= limit:
            break

    out.sort(key=lambda x: x['ts'])
    if not quiet:
        print(f"✅ ops 运维记录命中 {len(out)} 条（扫描 {len(records)} 条）\n")
    return out


def get_detail(record_id: str, quiet: bool = False) -> Optional[Dict]:
    data = _run_cs_cli(['ops-record', 'get', record_id])
    if data and data.get('success'):
        return data.get('data')
    if not quiet:
        print(f"❌ 获取详情失败: {record_id}")
    return None


def main():
    parser = argparse.ArgumentParser(description='ops 运维日志查询工具 (cs-cli ops-record)')
    parser.add_argument('--check', action='store_true', help='验证 cs-cli 认证')
    parser.add_argument('--start', help='开始时间 (ISO 8601，按 created_at 过滤)')
    parser.add_argument('--end', help='结束时间')
    parser.add_argument('--workspace', help='工作空间 ID')
    parser.add_argument('--agent', help='Agent ID')
    parser.add_argument('--operator', help='操作人花名（子串匹配）')
    parser.add_argument('--keyword', help='关键词（匹配 remark/path）')
    parser.add_argument('--limit', type=int, default=200, help='最大返回条数（默认 200）')
    parser.add_argument('--record-id', help='查询单条记录详情')
    parser.add_argument('--output', help='保存 JSON 文件路径')
    args = parser.parse_args()

    if args.check:
        sys.exit(0 if check() else 1)

    if args.record_id:
        detail = get_detail(args.record_id)
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        if args.output:
            Path(args.output).write_text(json.dumps(detail, ensure_ascii=False, indent=1), encoding='utf-8')
        return

    records = list_records(
        start=args.start, end=args.end, workspace=args.workspace,
        agent=args.agent, operator=args.operator, keyword=args.keyword,
        limit=args.limit, quiet=bool(args.output),
    )
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=1)
        print(f"💾 已保存 {len(records)} 条 → {out}")
    else:
        for i, r in enumerate(records, 1):
            print(f"[{i:>3}] {r['time']} | {r['operator']} | agent={str(r['agent_id'])[:12]}… | {str(r['remark'])[:80]}")


if __name__ == '__main__':
    main()
