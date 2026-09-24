#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务端日志查询工具 - 从阿里云 SLS (bty-prod-ack-log / customer-servhub-api)
拉取 customer-servhub-api 服务端日志。

支撑功能区：多方日志交叉分析（服务端 + RPA + ops 运维日志）。

示例:
  # 验证连接
  python3 server_log_query.py --check

  # 按会话 ID 查询
  python3 server_log_query.py --conversation-id dbc7a1d8... --start ... --end ...

  # 按 trace_id / request_id / dispatch_id 查询
  python3 server_log_query.py --trace-id 2e183865... --start ... --end ...

  # 只看报错日志
  python3 server_log_query.py --query "..." --level ERROR --start ... --end ...

  # 保存 JSON（供 cross_analysis.py 交叉分析使用）
  python3 server_log_query.py --conversation-id ... --output ../temp/server.json
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# BetterYeah 业务统一用北京时间(UTC+8)：分析师输入的时间窗、日志展示时间均为北京时间。
# 显式固定时区，使工具在非北京时区的主机上也给出一致结果（分发包可能跑在任意时区）。
CST = timezone(timedelta(hours=8))


def _parse_input_dt(s: str) -> datetime:
    """把分析师输入的 ISO 时间按北京时间解释；已带时区偏移的输入则原样尊重。"""
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=CST)

sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

try:
    from aliyun.log import LogClient, GetLogsRequest
except ImportError:
    print("❌ 缺少依赖: pip install aliyun-log-python-sdk")
    sys.exit(1)

def default_config_path() -> Path:
    """channels.json 查找顺序: 环境变量 CSDBG_CONFIG(npm CLI 安装模式) > 脚本同目录
    (zip 分发模式) > ~/.csdbg/channels.json(CLI 数据目录兜底)。--config 参数优先于一切。"""
    env = os.environ.get("CSDBG_CONFIG")
    if env:
        return Path(env)
    local = Path(__file__).parent / "channels.json"
    if local.exists():
        return local
    return Path.home() / ".csdbg" / "channels.json"

CONFIG_PATH = default_config_path()

# 从 message 正文中提取业务 ID 的正则
ID_PATTERNS = {
    'conversation_id': re.compile(r'con(?:versation)?[ _-]?id[=:\s\"\']*([a-f0-9]{16,64})', re.I),
    'record_id': re.compile(r'record[ _-]?id[=:\s\"\']*([a-f0-9]{16,64})', re.I),
    'request_id': re.compile(r'request[ _-]?id[=:\s\"\']*([a-f0-9]{16,64})', re.I),
    'dispatch_id': re.compile(r'dispatch[ _-]?id[=:\s\"\']*([a-f0-9]{16,64})', re.I),
    'trace_id': re.compile(r'trace[ _-]?id[=:\s\"\']*([a-f0-9]{16,64})', re.I),
    'agent_id': re.compile(r'agent[ _-]?(?:config)?[ _-]?id[=:\s\"\']*([a-f0-9]{16,64})', re.I),
    'workspace_id': re.compile(r'workspace[ _-]?id[=:\s\"\']*([a-f0-9]{16,64})', re.I),
    'equipment_id': re.compile(r'equipment[ _-]?id[=:\s\"\']*([a-f0-9]{16,64})', re.I),
    'user_id': re.compile(r'user[ _-]?id[=:\s\"\']*([A-Za-z0-9_\-\u4e00-\u9fff]{4,64})', re.I),
}

HEX32 = re.compile(r'\b[0-9a-f]{32}\b')


class ServerLogQuery:
    def __init__(self, config_path: str = None):
        with open(config_path or CONFIG_PATH, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        self.project = self.config['server_project']
        self.logstore = self.config['server']['logstore']
        self.client = LogClient(
            self.config['endpoint'],
            self.config['access_key_id'],
            self.config['access_key_secret'],
        )

    def check_connection(self) -> bool:
        try:
            ts = int(time.time())
            req = GetLogsRequest(self.project, self.logstore, ts - 60, ts, query='', line=1)
            self.client.get_logs(req)
            print(f"✅ 服务端日志连接正常")
            print(f"  Project : {self.project}")
            print(f"  Logstore: {self.logstore}")
            return True
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False

    def query(
        self,
        start_time: str,
        end_time: str,
        conversation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        request_id: Optional[str] = None,
        dispatch_id: Optional[str] = None,
        query_text: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 1000,
        quiet: bool = False,
    ) -> List[Dict]:
        """查询服务端日志，返回规范化后的记录列表（按时间升序）。"""
        # 对用户输入做引号/反斜杠转义，防止破坏 SLS 查询语法
        def _esc(v: str) -> str:
            return v.replace('\\', '\\\\').replace('"', '\\"')

        parts = []
        for v in (conversation_id, trace_id, request_id, dispatch_id):
            if v:
                parts.append(f'"{_esc(v)}"')
        if query_text:
            parts.append(f'"{_esc(query_text)}"')
        query_string = ' and '.join(parts) if parts else '*'

        from_ts = int(_parse_input_dt(start_time).timestamp())
        to_ts = int(_parse_input_dt(end_time).timestamp())

        if not quiet:
            print("📊 查询参数:")
            print(f"  来源    : 服务端 {self.project}/{self.logstore}")
            print(f"  时间范围: {start_time} ~ {end_time}")
            print(f"  查询语句: {query_string}")

        logs: List[Dict] = []
        offset, page = 0, 100
        while len(logs) < limit:
            want = min(page, limit - len(logs))
            req = GetLogsRequest(
                self.project, self.logstore, from_ts, to_ts,
                topic='', query=query_string, line=want,
                offset=offset, reverse=False,
            )
            resp = self.client.get_logs(req)
            batch = resp.get_logs()
            if not batch:
                break
            for log in batch:
                logs.append(self._normalize(log))
            if len(batch) < want:
                break
            offset += len(batch)

        # 级别过滤（客户端做，避免依赖字段索引）
        if level:
            logs = [l for l in logs if l['level'].upper() == level.upper()]

        if not quiet:
            print(f"✅ 查询成功，返回 {len(logs)} 条日志\n")
        return logs

    @staticmethod
    def _normalize(log) -> Dict:
        c = dict(log.get_contents())
        msg = c.get('message', '')
        rec = {
            'source': 'server',
            'ts': int(log.get_time()),
            'time': datetime.fromtimestamp(log.get_time(), tz=CST).strftime('%Y-%m-%d %H:%M:%S'),
            'level': c.get('levelname', ''),
            'message': msg,
            'module': c.get('pathname', '').rsplit('/', 1)[-1],
            'trace_id': c.get('otelTraceID', '') if c.get('otelTraceID') not in (None, '0') else '',
            'request_id': c.get('ws_request_id', '') or c.get('request_id', ''),
            'dispatch_id': c.get('dispatch_id', ''),
            'ws_type': c.get('ws_type', ''),
            'send_ids': c.get('send_ids', ''),
            'pod': c.get('__tag__:_container_ip_', ''),
        }
        # 从结构化字段与 message 正文提取业务 ID
        ids: Dict[str, List[str]] = {}
        haystack = msg + ' ' + rec['send_ids']
        for name, pat in ID_PATTERNS.items():
            found = pat.findall(haystack)
            if found:
                ids[name] = sorted(set(found))
        # 兜底：正文中出现的裸 32 位 hex（多为 conversation/record id）
        raw_hex = HEX32.findall(msg)
        if raw_hex:
            ids['hex_candidates'] = sorted(set(raw_hex))
        rec['ids'] = ids
        return rec


def format_timeline(logs: List[Dict]):
    if not logs:
        print("无日志数据")
        return
    print("=" * 100)
    print("服务端日志时间线")
    print("=" * 100)
    for i, log in enumerate(sorted(logs, key=lambda x: x['ts']), 1):
        print(f"[{i:>3}] {log['time']} [{log['level']:<7}] {log['module']}")
        print(f"      {log['message'][:160]}")


def main():
    parser = argparse.ArgumentParser(description='服务端日志查询工具 (customer-servhub-api)')
    parser.add_argument('--check', action='store_true', help='验证 SLS 连接')
    parser.add_argument('--conversation-id', help='会话 ID（全文匹配）')
    parser.add_argument('--trace-id', help='otelTraceID / trace_id')
    parser.add_argument('--request-id', help='ws_request_id')
    parser.add_argument('--dispatch-id', help='dispatch_id（RPA 下发）')
    parser.add_argument('--query', dest='query_text', help='关键词全文搜索')
    parser.add_argument('--level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='按日志级别过滤')
    parser.add_argument('--start', help='开始时间 (ISO 8601: 2026-09-18T10:30:00)')
    parser.add_argument('--end', help='结束时间')
    parser.add_argument('--limit', type=int, default=1000, help='最大返回条数（默认 1000）')
    parser.add_argument('--timeline', action='store_true', help='控制台输出时间线')
    parser.add_argument('--output', help='保存 JSON 文件路径')
    parser.add_argument('--config', help='自定义配置文件路径')
    args = parser.parse_args()

    q = ServerLogQuery(args.config)
    if args.check:
        sys.exit(0 if q.check_connection() else 1)

    if not (args.start and args.end):
        parser.error('查询需要 --start 和 --end')

    logs = q.query(
        start_time=args.start, end_time=args.end,
        conversation_id=args.conversation_id, trace_id=args.trace_id,
        request_id=args.request_id, dispatch_id=args.dispatch_id,
        query_text=args.query_text, level=args.level, limit=args.limit,
    )
    if args.timeline:
        format_timeline(logs)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=1)
        print(f"💾 已保存 {len(logs)} 条 → {out}")
    if not args.timeline and not args.output:
        format_timeline(logs)


if __name__ == '__main__':
    main()
