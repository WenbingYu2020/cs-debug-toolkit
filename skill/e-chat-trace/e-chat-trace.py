#!/usr/bin/env python3
"""
E-Chat-Trace: 电商客服消息全链路排查工具

核心模块:
1. ChannelDetector - 渠道识别
2. ConversationFetcher - 会话数据拉取
3. AgentLogFetcher - Agent 日志查询（SLS）
4. RPALogFetcher - RPA 日志查询（SLS）
5. IssueAnalyzer - 问题分析器
6. ReportGenerator - 报告生成器
"""

import sys
import json
import subprocess
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional, Tuple

# 阿里云 SLS 配置
SLS_CONFIG = {
    'endpoint': 'cn-hangzhou.log.aliyuncs.com',
    'region': 'cn-hangzhou',

    # Agent 日志
    'agent': {
        'project': 'bty-prod-ack-log',
        'logstore': 'customer-servhub-api'
    },

    # RPA 日志
    'rpa': {
        'project': 'customer-servhub-log',
        'logstores': {
            'qianniu': 'qianniu-rpa-new-prod',
            'douyin': 'project-douyin-rpa-prod',
            'jd': 'project-jd-rpa-prod',
            'pdd': 'project-pdd-rpa-prod'
        }
    }
}

TZ = ZoneInfo('Asia/Shanghai')

# ============================================================================
# Helper Functions
# ============================================================================

def exec_cmd(cmd: List[str]) -> str:
    """执行命令并返回输出"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed: {' '.join(cmd)}")
        print(f"Error: {e.stderr}")
        sys.exit(1)

def parse_json_output(text: str) -> dict:
    """解析 cs-cli JSON 输出，处理尾部噪音"""
    # cs-cli 可能在 JSON 后面有版本更新提示等，使用 JSONDecoder().raw_decode() 只解析第一个完整 JSON
    import json
    decoder = json.JSONDecoder()
    try:
        obj, idx = decoder.raw_decode(text)
        return obj
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析失败: {e}")
        print(f"Output:\n{text[:500]}")
        sys.exit(1)

def format_time(ts: any) -> str:
    """格式化时间戳"""
    if not ts:
        return ""
    if isinstance(ts, str):
        # ISO 格式
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    elif isinstance(ts, (int, float)):
        # Unix timestamp
        dt = datetime.fromtimestamp(ts, tz=TZ)
    else:
        return str(ts)

    return dt.astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S')

def parse_duration(seconds: any) -> str:
    """格式化时长"""
    if not seconds:
        return "0秒"

    if isinstance(seconds, str):
        seconds = float(seconds)

    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}分{secs:.0f}秒"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}小时{minutes}分"

# ============================================================================
# 1. Channel Detector
# ============================================================================

class ChannelDetector:
    """渠道识别器"""

    CHANNEL_PATTERNS = {
        'qianniu': [
            re.compile(r'千牛|淘宝|天猫|taobao|tmall', re.I),
            re.compile(r'^tb_', re.I),
            re.compile(r'\.PNM$', re.I)  # 千牛消息 ID 格式
        ],
        'douyin': [
            re.compile(r'抖音|douyin|抖店', re.I),
            re.compile(r'^dy_', re.I)
        ],
        'jd': [
            re.compile(r'京东|jd', re.I),
            re.compile(r'^jd[_-]', re.I)
        ],
        'pdd': [
            re.compile(r'拼多多|pinduoduo|pdd', re.I),
            re.compile(r'^pdd_', re.I)
        ]
    }

    @classmethod
    def detect(cls, conv_data: dict) -> str:
        """
        从 conversation 数据中识别渠道

        识别依据（按优先级）:
        1. role_name / role_id 包含渠道关键词
        2. user_name 前缀
        3. equipment_id 格式
        4. 兜底: qianniu（最常见）
        """
        # 1. 检查 role_name
        role_name = conv_data.get('role_name', '')
        for channel, patterns in cls.CHANNEL_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(role_name):
                    return channel

        # 2. 检查 user_name
        user_name = conv_data.get('user_name', '')
        for channel, patterns in cls.CHANNEL_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(user_name):
                    return channel

        # 3. 检查 equipment_id
        equipment_id = conv_data.get('equipment_id', '')
        for channel, patterns in cls.CHANNEL_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(equipment_id):
                    return channel

        # 4. 兜底
        print("⚠️  无法自动识别渠道，默认使用 千牛")
        return 'qianniu'

    @classmethod
    def get_logstore(cls, channel: str) -> str:
        """获取对应的 RPA SLS logstore"""
        return SLS_CONFIG['rpa']['logstores'].get(channel, 'qianniu-rpa-new-prod')

    @classmethod
    def get_channel_name(cls, channel: str) -> str:
        """获取渠道中文名"""
        names = {
            'qianniu': '千牛（淘宝/天猫）',
            'douyin': '抖音',
            'jd': '京东',
            'pdd': '拼多多'
        }
        return names.get(channel, channel)

# ============================================================================
# 2. Conversation Fetcher
# ============================================================================

class ConversationFetcher:
    """会话数据拉取器"""

    @staticmethod
    def fetch_records(conversation_id: str) -> List[dict]:
        """拉取会话消息记录"""
        print(f"📥 拉取会话消息记录: {conversation_id}")

        cmd = ['cs-cli', 'conversation', 'records', conversation_id, '--page-size', '100']
        output = exec_cmd(cmd)
        data = parse_json_output(output)

        records = data.get('data', {}).get('records', [])
        print(f"   ✅ 拉取到 {len(records)} 条消息")

        return records

    @staticmethod
    def get_conversation_info(conversation_id: str) -> dict:
        """从第一条消息获取会话基本信息"""
        # cs-cli conversation list 需要其他筛选条件，直接从 records 获取
        records = ConversationFetcher.fetch_records(conversation_id)
        if not records:
            return {}

        first_msg = records[-1]  # records 是倒序的
        return {
            'conversation_id': conversation_id,
            'user_name': first_msg.get('user_name'),
            'role_name': first_msg.get('role_name'),
            'role_id': first_msg.get('role_id'),
            'equipment_id': first_msg.get('equipment_id'),
            'created_at': first_msg.get('created_at')
        }

# ============================================================================
# 3. Agent Log Fetcher (SLS)
# ============================================================================

class AgentLogFetcher:
    """Agent 日志查询器（从 SLS 直接查询）"""

    def __init__(self):
        # 检查环境变量
        self.access_key_id = os.environ.get('ALIYUN_ACCESS_KEY_ID')
        self.access_key_secret = os.environ.get('ALIYUN_ACCESS_KEY_SECRET')

        if not self.access_key_id or not self.access_key_secret:
            print("⚠️  未配置阿里云 SLS 凭证")
            print("   请设置环境变量:")
            print("   export ALIYUN_ACCESS_KEY_ID=<your_key>")
            print("   export ALIYUN_ACCESS_KEY_SECRET=<your_secret>")
            self.enabled = False
        else:
            self.enabled = True

    def fetch_logs(self, conversation_id: str, from_time: int, to_time: int) -> List[dict]:
        """查询 Agent 日志"""
        if not self.enabled:
            print("⚠️  跳过 Agent 日志查询（未配置凭证）")
            return []

        print(f"🔍 查询 Agent 日志")
        print(f"   项目: {SLS_CONFIG['agent']['project']}/{SLS_CONFIG['agent']['logstore']}")
        print(f"   会话 ID: {conversation_id}")
        print(f"   时间范围: {format_time(from_time)} - {format_time(to_time)}")

        try:
            from aliyun.log import LogClient

            client = LogClient(
                SLS_CONFIG['endpoint'],
                self.access_key_id,
                self.access_key_secret
            )

            # SLS SQL 查询 - 按 conversation_id 全文搜索
            sql = f'"{conversation_id}" | SELECT * LIMIT 100'

            response = client.execute_logstore_sql(
                SLS_CONFIG['agent']['project'],
                SLS_CONFIG['agent']['logstore'],
                from_time, to_time, sql, False
            )

            logs = response.get_logs()
            print(f"   ✅ 拉取到 {len(logs)} 条日志")

            return logs

        except ImportError:
            print("⚠️  aliyun-log-python-sdk 未安装")
            print("   请安装: pip install aliyun-log-python-sdk")
            return []
        except Exception as e:
            print(f"⚠️  Agent 日志查询失败: {e}")
            return []

    @staticmethod
    def filter_logs_by_record(logs: List[dict], record_ids: List[str]) -> Dict[str, List[dict]]:
        """按 record_id 过滤 Agent 日志"""
        result = {rid: [] for rid in record_ids}

        for log in logs:
            content = log.get('contents', {})
            record_id = content.get('record_id', '')

            if record_id in result:
                result[record_id].append(log)

        return result

    @staticmethod
    def analyze_agent_log(logs: List[dict]) -> dict:
        """分析单条消息的 Agent 日志"""
        if not logs:
            return {}

        # 合并所有日志（一条 Agent 回复可能有多条日志）
        analysis = {
            'total_duration': 0,
            'llm_duration': 0,
            'event_one': '',
            'event_two': '',
            'behavior_situation': '',
            'behavior_action': '',
            'tool_calls': [],
            'transfer_to_human': False,
            'error_message': '',
            'stages': {}
        }

        for log in logs:
            content = log.get('contents', {})

            # 提取关键字段
            if 'total_duration' in content:
                analysis['total_duration'] = max(analysis['total_duration'],
                                                  float(content.get('total_duration', 0)))

            if 'llm_duration' in content:
                analysis['llm_duration'] = max(analysis['llm_duration'],
                                                float(content.get('llm_duration', 0)))

            if 'event_one' in content and not analysis['event_one']:
                analysis['event_one'] = content.get('event_one', '')

            if 'event_two' in content and not analysis['event_two']:
                analysis['event_two'] = content.get('event_two', '')

            if 'behavior_situation' in content:
                analysis['behavior_situation'] = content.get('behavior_situation', '')

            if 'behavior_action' in content:
                analysis['behavior_action'] = content.get('behavior_action', '')

            if 'tool_calls' in content:
                analysis['tool_calls'].extend(json.loads(content.get('tool_calls', '[]')))

            if 'transfer_to_human' in content:
                analysis['transfer_to_human'] = content.get('transfer_to_human', '').lower() == 'true'

            if 'error_message' in content and content.get('error_message'):
                analysis['error_message'] = content.get('error_message', '')

            # 提取各阶段耗时
            for key, value in content.items():
                if key.endswith('_duration') or key.endswith('_time'):
                    try:
                        analysis['stages'][key] = float(value)
                    except:
                        pass

        return analysis

# ============================================================================
# 4. RPA Log Fetcher
# ============================================================================

class RPALogFetcher:
    """RPA 日志查询器"""

    def __init__(self):
        # 检查环境变量
        self.access_key_id = os.environ.get('ALIYUN_ACCESS_KEY_ID')
        self.access_key_secret = os.environ.get('ALIYUN_ACCESS_KEY_SECRET')

        if not self.access_key_id or not self.access_key_secret:
            print("⚠️  未配置阿里云 SLS 凭证")
            print("   请设置环境变量:")
            print("   export ALIYUN_ACCESS_KEY_ID=<your_key>")
            print("   export ALIYUN_ACCESS_KEY_SECRET=<your_secret>")
            self.enabled = False
        else:
            self.enabled = True

    def fetch_logs(self, logstore: str, shop_name: str,
                   from_time: int, to_time: int) -> List[dict]:
        """查询 RPA 日志"""
        if not self.enabled:
            print("⚠️  跳过 RPA 日志查询（未配置凭证）")
            return []

        print(f"📋 查询 RPA 日志: {logstore}")
        print(f"   时间范围: {format_time(from_time)} - {format_time(to_time)}")
        print(f"   店铺: {shop_name}")

        try:
            from aliyun.log import LogClient

            client = LogClient(
                SLS_CONFIG['endpoint'],
                self.access_key_id,
                self.access_key_secret
            )

            # SLS SQL 查询
            sql = f"{shop_name} | SELECT * LIMIT 500"

            response = client.execute_logstore_sql(
                SLS_CONFIG['rpa']['project'], logstore,
                from_time, to_time, sql, False
            )

            logs = response.get_logs()
            print(f"   ✅ 拉取到 {len(logs)} 条日志")

            return logs

        except ImportError:
            print("⚠️  aliyun-log-python-sdk 未安装")
            print("   请安装: pip install aliyun-log-python-sdk")
            return []
        except Exception as e:
            print(f"⚠️  RPA 日志查询失败: {e}")
            return []

    @staticmethod
    def filter_logs_by_conversation(logs: List[dict], conversation_id: str,
                                     user_name: str) -> List[dict]:
        """按会话 ID 和用户名过滤日志"""
        filtered = []
        for log in logs:
            content = log.get('contents', {})

            # 检查 conversation_id
            if conversation_id in str(content):
                filtered.append(log)
                continue

            # 检查 user_name
            if user_name and user_name in str(content):
                filtered.append(log)
                continue

        return filtered

# ============================================================================
# 5. Issue Analyzer
# ============================================================================

class IssueAnalyzer:
    """问题分析器 - 基于 4 案例经验"""

    RPA_PATTERNS = {
        '发送队列堵塞': {
            'keywords': ['reply-message 入队', '发送消息成功', 'reply-message'],
            'severity': '🔴 严重'
        },
        '面板串台误判': {
            'keywords': ['新用户面板昵称已属其他会话', '串台', '暂不建会话'],
            'severity': '🔴 严重'
        },
        '面板未确认重试': {
            'keywords': ['面板未确认', '匹配待确认', 'count='],
            'severity': '🔴🔴 极严重'
        },
        '处理队列排队': {
            'keywords': ['列表快照', '接待='],
            'severity': '🟡 中等'
        },
        '欢迎语发送': {
            'keywords': ['欢迎语发送成功'],
            'severity': '✅ 正常'
        }
    }

    @staticmethod
    def detect_message_delays(records: List[dict]) -> List[dict]:
        """检测消息延迟"""
        delays = []

        for msg in records:
            if msg.get('category') != 'agent_response':
                continue

            reply_time = msg.get('reply_time')
            created_at = msg.get('created_at')
            agent_time = msg.get('agent_duration_time', 0)

            if not reply_time or not created_at:
                continue

            # 计算总延迟（秒）
            reply_dt = datetime.fromisoformat(reply_time.replace('Z', '+00:00'))
            created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            total_delay = (reply_dt - created_dt).total_seconds()

            if total_delay > 60:  # 超过 60 秒
                non_agent_time = total_delay - float(agent_time or 0)

                delays.append({
                    'record_id': msg.get('record_id'),
                    'message_time': msg.get('message_time'),
                    'total_delay': total_delay,
                    'agent_time': float(agent_time or 0),
                    'non_agent_time': non_agent_time,
                    'text': msg.get('context', {}).get('text', '')[:50]
                })

        return delays

    @staticmethod
    def detect_welcome_delay(records: List[dict]) -> Optional[dict]:
        """检测欢迎语延迟"""
        # 找到第一条用户消息
        first_user = None
        for msg in reversed(records):  # records 是倒序的
            if msg.get('role') == 'user':
                first_user = msg
                break

        if not first_user:
            return None

        # 找到欢迎语
        welcome = None
        for msg in records:
            text = msg.get('context', {}).get('text', '')
            if '您好' in text and '很高兴' in text and msg.get('role') == 'assistant':
                welcome = msg
                break

        if not welcome:
            return None

        # 计算延迟
        user_time = datetime.fromisoformat(first_user.get('message_time').replace('Z', '+00:00'))
        welcome_time = datetime.fromisoformat(welcome.get('message_time').replace('Z', '+00:00'))
        delay = (welcome_time - user_time).total_seconds()

        if delay > 30:  # 超过 30 秒
            return {
                'user_time': first_user.get('message_time'),
                'welcome_time': welcome.get('message_time'),
                'delay': delay,
                'record_id': welcome.get('record_id')
            }

        return None

    @staticmethod
    def identify_rpa_patterns(logs: List[dict]) -> List[dict]:
        """识别 RPA 日志模式"""
        patterns_found = []

        for pattern_name, config in IssueAnalyzer.RPA_PATTERNS.items():
            keywords = config['keywords']
            matched_logs = []

            for log in logs:
                content_str = str(log.get('contents', {}))
                if any(kw in content_str for kw in keywords):
                    matched_logs.append(log)

            if matched_logs:
                patterns_found.append({
                    'pattern': pattern_name,
                    'severity': config['severity'],
                    'count': len(matched_logs),
                    'logs': matched_logs
                })

        return patterns_found

# ============================================================================
# 6. Report Generator
# ============================================================================

class ReportGenerator:
    """报告生成器"""

    @staticmethod
    def generate(conversation_id: str, channel: str, conv_info: dict,
                 records: List[dict], delays: List[dict],
                 welcome_delay: Optional[dict], agent_traces: dict,
                 rpa_patterns: List[dict]):
        """生成终端报告"""

        print("\n" + "=" * 80)
        print("           E-Chat 消息链路排查报告")
        print("=" * 80)
        print()
        print(f"会话 ID: {conversation_id}")
        print(f"渠道: {ChannelDetector.get_channel_name(channel)}")
        print(f"店铺: {conv_info.get('role_name', 'N/A')}")
        print(f"用户: {conv_info.get('user_name', 'N/A')}")

        if records:
            first_time = records[-1].get('message_time')
            last_time = records[0].get('message_time')
            print(f"时间: {format_time(first_time)} - {format_time(last_time)}")

        print()
        print("=" * 80)
        print("核心结论")
        print("=" * 80)
        print()

        # 汇总结论
        if delays:
            print(f"🔴 检测到 {len(delays)} 条 Agent 回复延迟")
            for d in delays:
                agent_pct = (d['agent_time'] / d['total_delay'] * 100) if d['total_delay'] > 0 else 0
                non_agent_pct = 100 - agent_pct

                print(f"\n消息: {d['text']}...")
                print(f"总延迟: {parse_duration(d['total_delay'])}")
                print(f"  • Agent 推理: {parse_duration(d['agent_time'])} ({agent_pct:.0f}%)")
                print(f"  • RPA + 其他: {parse_duration(d['non_agent_time'])} ({non_agent_pct:.0f}%)")

                if non_agent_pct > 50:
                    print(f"  → 主因: RPA 侧")
                elif agent_pct > 50:
                    print(f"  → 主因: Agent 侧")
                else:
                    print(f"  → 主因: 混合")

        if welcome_delay:
            print(f"\n🔴 检测到欢迎语延迟: {parse_duration(welcome_delay['delay'])}")
            print(f"  用户进线: {format_time(welcome_delay['user_time'])}")
            print(f"  欢迎语发送: {format_time(welcome_delay['welcome_time'])}")

        if not delays and not welcome_delay:
            print("✅ 未检测到明显延迟问题")

        print()
        print("=" * 80)
        print("消息时间线")
        print("=" * 80)
        print()

        # 打印消息时间线
        for msg in reversed(records[-10:]):  # 最近 10 条
            role_icon = "👤" if msg.get('role') == 'user' else "🤖"
            category = msg.get('category', '')
            text = msg.get('context', {}).get('text', '')[:40]
            msg_time = format_time(msg.get('message_time'))

            print(f"{msg_time} {role_icon} [{category}] {text}...")

        # Agent 日志分析
        if agent_traces:
            print()
            print("=" * 80)
            print("Agent 日志分析（SLS: bty-prod-ack-log/customer-servhub-api）")
            print("=" * 80)
            print()

            for record_id, analysis in agent_traces.items():
                print(f"Record ID: {record_id}")

                total_dur = analysis.get('total_duration', 0)
                llm_dur = analysis.get('llm_duration', 0)

                print(f"总处理耗时: {parse_duration(total_dur)}")
                print(f"LLM 推理耗时: {parse_duration(llm_dur)}")

                if total_dur < 15:
                    print("  ✅ 推理时长正常")
                elif total_dur < 30:
                    print("  ⚠️  推理时长偏慢")
                else:
                    print("  🔴 推理时长异常")

                event_one = analysis.get('event_one', 'N/A')
                event_two = analysis.get('event_two', 'N/A')
                print(f"意图识别: {event_one} / {event_two}")

                situation = analysis.get('behavior_situation', '')
                if situation:
                    print(f"SOP 命中: {situation[:80]}")
                else:
                    print(f"SOP 命中: 无")

                if analysis.get('transfer_to_human'):
                    print("  ⚠️  转人工")

                if analysis.get('error_message'):
                    print(f"  🔴 错误: {analysis['error_message']}")

                # 各阶段耗时
                stages = analysis.get('stages', {})
                if stages:
                    print(f"各阶段耗时:")
                    for stage, dur in sorted(stages.items(), key=lambda x: -x[1]):
                        if dur > 0.5:  # 只显示 > 0.5 秒的阶段
                            print(f"  • {stage}: {parse_duration(dur)}")

                print()

        # RPA 日志分析
        if rpa_patterns:
            print()
            print("=" * 80)
            print("RPA 日志分析")
            print("=" * 80)
            print()

            for pattern in rpa_patterns:
                print(f"{pattern['severity']} {pattern['pattern']}: {pattern['count']} 条相关日志")

                # 打印关键日志（前 3 条）
                for log in pattern['logs'][:3]:
                    time_str = log.get('__time__', '')
                    if time_str:
                        time_str = format_time(int(time_str))
                    content = log.get('contents', {})
                    # 提取关键信息
                    msg = content.get('message', str(content)[:100])
                    print(f"  [{time_str}] {msg}")

                print()

        # 修复建议
        print()
        print("=" * 80)
        print("修复建议")
        print("=" * 80)
        print()

        if delays:
            print("🔴 P0: 优化 RPA 发送队列")
            print("   • 增加发送并发能力")
            print("   • 提高 Agent 回复优先级")
            print()

        if welcome_delay:
            print("🔴 P0: 优化欢迎语发送机制")
            print("   • 欢迎语最高优先级")
            print("   • 事件驱动，不排队")
            print()

        if any(p['pattern'] == '面板串台误判' for p in rpa_patterns):
            print("🔴🔴 P0: 使用 user_id 替代昵称匹配")
            print("   • 淘宝 API 返回的 user_id 作为唯一标识")
            print("   • 支持昵称别名机制")
            print()

        if any(p['pattern'] == '面板未确认重试' for p in rpa_patterns):
            print("🔴🔴 P0: 优化面板确认重试机制")
            print("   • 重试间隔: 70-97秒 → 5-10秒")
            print("   • 使用 API 而非 UI 点击")
            print()

        print("=" * 80)
        print()

# ============================================================================
# Main
# ============================================================================

def main():
    """主入口"""
    if len(sys.argv) < 2:
        print("Usage: e-chat-trace.py <conversation_id> [target_message]")
        print()
        print("Examples:")
        print("  e-chat-trace.py 0123456789abcdef0123456789abcdef")
        print("  e-chat-trace.py 0123456789abcdef0123456789abcdef '您好，很高兴为您服务。'")
        sys.exit(1)

    conversation_id = sys.argv[1]
    target_message = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"🚀 E-Chat 消息链路排查")
    print(f"   会话 ID: {conversation_id}")
    if target_message:
        print(f"   目标消息: {target_message}")
    print()

    # 1. 拉取会话信息
    conv_info = ConversationFetcher.get_conversation_info(conversation_id)

    # 2. 识别渠道
    channel = ChannelDetector.detect(conv_info)
    logstore = ChannelDetector.get_logstore(channel)
    print(f"📍 识别渠道: {ChannelDetector.get_channel_name(channel)}")
    print(f"   Logstore: {logstore}")
    print()

    # 3. 拉取消息记录
    records = ConversationFetcher.fetch_records(conversation_id)

    # 4. 异常检测
    print("🔍 检测异常...")
    delays = IssueAnalyzer.detect_message_delays(records)
    welcome_delay = IssueAnalyzer.detect_welcome_delay(records)
    print(f"   Agent 回复延迟: {len(delays)} 条")
    if welcome_delay:
        print(f"   欢迎语延迟: {parse_duration(welcome_delay['delay'])}")
    print()

    # 确定时间范围（第一条到最后一条消息前后 5 分钟）
    if records:
        first_time = datetime.fromisoformat(records[-1].get('message_time').replace('Z', '+00:00'))
        last_time = datetime.fromisoformat(records[0].get('message_time').replace('Z', '+00:00'))
        from_time = int((first_time - timedelta(minutes=5)).timestamp())
        to_time = int((last_time + timedelta(minutes=5)).timestamp())
    else:
        # 兜底：最近 1 小时
        to_time = int(datetime.now(TZ).timestamp())
        from_time = to_time - 3600

    # 5. 拉取 Agent 日志（SLS）
    agent_analysis = {}
    agent_fetcher = AgentLogFetcher()

    if agent_fetcher.enabled and delays:
        agent_logs = agent_fetcher.fetch_logs(conversation_id, from_time, to_time)

        # 按 record_id 过滤
        record_ids = [d['record_id'] for d in delays]
        agent_logs_by_record = AgentLogFetcher.filter_logs_by_record(agent_logs, record_ids)

        # 分析每条消息的 Agent 日志
        for record_id, logs in agent_logs_by_record.items():
            if logs:
                agent_analysis[record_id] = AgentLogFetcher.analyze_agent_log(logs)

    # 6. 拉取 RPA 日志（SLS）
    rpa_patterns = []
    rpa_fetcher = RPALogFetcher()

    if rpa_fetcher.enabled and records:
        shop_name = conv_info.get('role_name', '')

        if shop_name:
            logs = rpa_fetcher.fetch_logs(logstore, shop_name, from_time, to_time)

            # 按会话 ID 过滤
            filtered_logs = RPALogFetcher.filter_logs_by_conversation(
                logs, conversation_id, conv_info.get('user_name', '')
            )
            print(f"   ✅ 过滤后剩余 {len(filtered_logs)} 条相关日志")
            print()

            # 识别模式
            rpa_patterns = IssueAnalyzer.identify_rpa_patterns(filtered_logs)

    # 7. 生成报告
    ReportGenerator.generate(
        conversation_id, channel, conv_info, records,
        delays, welcome_delay, agent_analysis, rpa_patterns
    )

    # 8. 清理临时文件
    cleanup_temp_files()

def cleanup_temp_files():
    """清理本次执行产生的临时文件"""
    import glob
    import tempfile

    temp_dir = tempfile.gettempdir()
    patterns = ['cs-cli-*.json', 'sls-logs-*.json', 'trace-*.json']

    cleaned = 0
    for pattern in patterns:
        for file in glob.glob(os.path.join(temp_dir, pattern)):
            try:
                os.remove(file)
                cleaned += 1
            except:
                pass

    if cleaned > 0:
        print(f"🧹 清理了 {cleaned} 个临时文件")

if __name__ == '__main__':
    main()
