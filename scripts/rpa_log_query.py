#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RPA 日志查询工具 - 从阿里云 SLS 拉取 RPA 日志并分析
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

# 设置 UTF-8 编码输出
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

# BetterYeah 业务统一用北京时间(UTC+8)；显式固定时区，非北京时区主机上也一致。
CST = timezone(timedelta(hours=8))


def _parse_input_dt(s: str) -> datetime:
    """把分析师输入的 ISO 时间按北京时间解释；已带时区偏移的输入原样尊重。"""
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=CST)

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


class RPALogQuery:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = default_config_path()

        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        self.client = LogClient(
            self.config['endpoint'],
            self.config['access_key_id'],
            self.config['access_key_secret']
        )

    def check_connection(self):
        """验证 SLS 连接"""
        try:
            project = self.config.get('project') or self.config.get('rpa_project')
            response = self.client.list_logstore(project)
            logstores = response.get_logstores()
            print(f"✅ 连接成功")
            print(f"Project: {project}")
            print(f"Endpoint: {self.config['endpoint']}")
            print(f"Logstore 数量: {len(logstores)}\n")
            print("所有 Logstore:")
            for ls in sorted(logstores):
                print(f"  - {ls}")
            return True
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False

    def list_channels(self):
        """列出所有配置的渠道"""
        print("已配置渠道:\n")
        for key, info in self.config['channels'].items():
            print(f"  {key:<12} - {info['name']:<8} | logstore: {info['logstore']}")

    def query(
        self,
        channel: str,
        start_time: str,
        end_time: str,
        equipment_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        query_text: Optional[str] = None,
        dev: bool = False,
        limit: int = 1000,
        quiet: bool = False
    ) -> List[Dict]:
        """
        查询 RPA 日志

        Args:
            channel: 渠道名称 (以 channels.json 配置为准)
            start_time: 开始时间 (ISO 8601 格式: 2026-08-22T10:30:00)
            end_time: 结束时间
            equipment_id: 设备 ID
            conversation_id: 会话 ID
            query_text: 消息内容搜索
            dev: 是否查询开发环境
            limit: 最大返回条数
            quiet: 静默模式（不打印查询参数/结果信息，供 cross/host-events 内嵌调用）

        Returns:
            日志列表
        """
        if channel not in self.config['channels']:
            raise ValueError(f"未知渠道: {channel}，支持: {list(self.config['channels'].keys())}")

        channel_info = self.config['channels'][channel]
        logstore = channel_info['dev_logstore'] if dev else channel_info['logstore']

        # 构建查询条件（对用户输入做引号/反斜杠转义，防止破坏 SLS 查询语法）
        def _esc(v: str) -> str:
            return v.replace('\\', '\\\\').replace('"', '\\"')

        query_parts = []
        if equipment_id:
            query_parts.append(f'"{_esc(equipment_id)}"')
        if conversation_id:
            query_parts.append(f'"{_esc(conversation_id)}"')
        if query_text:
            query_parts.append(f'"{_esc(query_text)}"')

        query_string = ' and '.join(query_parts) if query_parts else '*'

        # 时间转换
        from_ts = int(_parse_input_dt(start_time).timestamp())
        to_ts = int(_parse_input_dt(end_time).timestamp())

        if not quiet:
            print(f"📊 查询参数:")
            print(f"  渠道: {channel_info['name']} ({channel})")
            print(f"  Logstore: {logstore}")
            print(f"  时间范围: {start_time} ~ {end_time}")
            print(f"  查询语句: {query_string}")
            print(f"  限制条数: {limit}\n")

        # 执行查询（翻页取满 limit；SLS GetLogs 单次 line 上限 100，与 server_log_query 对齐）
        logs: List[Dict] = []
        offset = 0
        page_size = min(limit or 100, 100)
        while len(logs) < limit:
            request = GetLogsRequest(
                self.config.get('project', self.config.get('rpa_project')),
                logstore,
                from_ts,
                to_ts,
                topic='',
                query=query_string,
                line=page_size,
                offset=offset,
                reverse=False
            )
            try:
                response = self.client.get_logs(request)
            except Exception as e:
                print(f"❌ 查询失败: {e}")
                return logs
            page = []
            for log in response.get_logs():
                log_dict = {
                    '__time__': log.get_time(),
                    '__source__': log.contents.get('__source__', ''),
                }
                log_dict.update(log.get_contents())
                page.append(log_dict)
            logs.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)

        if not quiet:
            print(f"✅ 查询成功，返回 {len(logs)} 条日志\n")
        return logs


def format_timeline(logs: List[Dict]):
    """格式化输出日志时间线"""
    if not logs:
        print("无日志数据")
        return

    # 按时间排序
    logs.sort(key=lambda x: int(x.get('__time__', 0)))

    print("="*100)
    print("日志时间线")
    print("="*100)

    first_ts = None
    for i, log in enumerate(logs, 1):
        ts = int(log.get('__time__', 0))
        dt = datetime.fromtimestamp(ts, tz=CST)
        time_str = dt.strftime('%H:%M:%S')

        if first_ts is None:
            first_ts = ts
            delta_str = '  0.0s'
        else:
            delta = ts - first_ts
            delta_str = f'+{delta:>6.1f}s'

        level = log.get('level', '')
        module = log.get('module', '')
        func = log.get('function', '')
        msg = log.get('message', '')[:100].replace('\n', ' ')

        print(f"[{i:>3}] {time_str} ({delta_str}) [{level:<5}] {module:<20} {func:<25}")
        print(f"      {msg}")

        # 高亮错误
        error_detail = log.get('error_detail', '')
        if error_detail:
            print(f"      ❌ ERROR: {error_detail}")


def main():
    parser = argparse.ArgumentParser(
        description='RPA 日志查询工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 验证连接
  python3 rpa_log_query.py --check

  # 列出所有渠道
  python3 rpa_log_query.py --list-channels

  # 查询抖音设备日志
  python3 rpa_log_query.py \\
    --channel douyin \\
    --equipment-id "abcdef0123456789abcdef0123456789" \\
    --start "2026-08-22T10:30:00" \\
    --end "2026-08-22T10:50:00"

  # 按消息内容搜索
  python3 rpa_log_query.py \\
    --channel douyin \\
    --query "亲~在的呢" \\
    --start "2026-08-22T10:00:00" \\
    --end "2026-08-22T11:00:00"

  # 按会话 ID 查询
  python3 rpa_log_query.py \\
    --channel pinduoduo \\
    --conversation-id "0123456789abcdef0123456789abcdef" \\
    --start "2026-08-22T10:00:00" \\
    --end "2026-08-22T11:00:00"
        """
    )

    parser.add_argument('--check', action='store_true', help='验证 SLS 连接')
    parser.add_argument('--list-channels', action='store_true', help='列出所有渠道')
    # 渠道名不设硬编码 choices：以 channels.json 配置为准（新增渠道无需改代码，query() 内有运行时校验）
    parser.add_argument('--channel', help='渠道名称')
    parser.add_argument('--equipment-id', help='设备 ID')
    parser.add_argument('--conversation-id', help='会话 ID')
    parser.add_argument('--query', help='消息内容搜索')
    parser.add_argument('--start', help='开始时间 (ISO 8601: 2026-08-22T10:30:00)')
    parser.add_argument('--end', help='结束时间')
    parser.add_argument('--dev', action='store_true', help='查询开发环境')
    parser.add_argument('--limit', type=int, default=1000, help='最大返回条数 (默认 1000)')
    parser.add_argument('--output', help='输出文件路径 (JSON 格式)')
    parser.add_argument('--config', help='配置文件路径 (默认: scripts/channels.json)')

    args = parser.parse_args()

    try:
        query_tool = RPALogQuery(args.config)
    except FileNotFoundError:
        print("❌ 配置文件不存在: scripts/channels.json")
        print("请先创建配置文件并填入 AK 信息")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        sys.exit(1)

    # 验证连接
    if args.check:
        sys.exit(0 if query_tool.check_connection() else 1)

    # 列出渠道
    if args.list_channels:
        query_tool.list_channels()
        return

    # 查询日志
    if not args.channel:
        print("❌ 缺少 --channel 参数")
        parser.print_help()
        sys.exit(1)

    if not args.start or not args.end:
        print("❌ 缺少 --start 和 --end 参数")
        parser.print_help()
        sys.exit(1)

    logs = query_tool.query(
        channel=args.channel,
        start_time=args.start,
        end_time=args.end,
        equipment_id=args.equipment_id,
        conversation_id=args.conversation_id,
        query_text=args.query,
        dev=args.dev,
        limit=args.limit
    )

    # 输出时间线
    format_timeline(logs)

    # 保存到文件
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 已保存到: {args.output}")


if __name__ == '__main__':
    main()
