#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RPA 日志分析 HTML 报告生成器
输入: rpa_log_query.py 生成的 JSON
输出: 自包含 HTML 报告
"""

import json
import sys
import html
from pathlib import Path
from datetime import datetime, timedelta, timezone

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# BetterYeah 业务统一北京时间(UTC+8)：报告展示按北京时间，非北京时区主机上也一致。
CST = timezone(timedelta(hours=8))


SCRIPT_DIR = Path(__file__).parent
TEMPLATE_PATH = SCRIPT_DIR.parent / 'templates' / 'rpa_log_report.html'


def esc(text):
    """HTML 转义"""
    if text is None:
        return ''
    return html.escape(str(text), quote=True)


def get_log_level(log_entry):
    """从日志内容中提取日志级别"""
    contents = log_entry.get('contents', {})
    if isinstance(contents, dict):
        level = contents.get('level', contents.get('__log_level__', ''))
        if level:
            return level.upper()
        # 从 message 中检测
        msg = str(contents.get('message', '') + contents.get('level_text', ''))
        for lvl in ['ERROR', 'WARNING', 'WARN', 'INFO', 'DEBUG']:
            if lvl in msg.upper()[:20]:
                return lvl
    return 'INFO'


def format_log_entry(log_entry):
    """格式化单条日志为 HTML"""
    ts = log_entry.get('timestamp', 0)
    if isinstance(ts, (int, float)):
        time_str = datetime.fromtimestamp(ts, tz=CST).strftime('%H:%M:%S')
    else:
        time_str = str(ts)[:19]

    contents = log_entry.get('contents', {})
    level = get_log_level(log_entry)
    level_class = level.lower() if level.lower() in ['error', 'warning', 'warn', 'info', 'debug'] else 'info'
    if level_class == 'warn':
        level_class = 'warning'

    # 提取消息内容
    if isinstance(contents, dict):
        message = contents.get('message', '') or contents.get('msg', '') or contents.get('content', '')
        if not message:
            # 展示所有字段
            message = json.dumps(contents, ensure_ascii=False, indent=None)[:500]
        module = contents.get('module', '') or contents.get('logger', '') or contents.get('source', '')
    else:
        message = str(contents)[:500]
        module = ''

    return f"""
        <div class="log-entry {level_class}">
            <div class="log-time">{esc(time_str)}</div>
            <div class="log-level {level_class}">{esc(level)}</div>
            <div class="log-message">{esc(message)}</div>
            <div class="log-tag">{esc(module)}</div>
        </div>
    """


def format_message(msg):
    """格式化会话消息为 HTML"""
    role = msg.get('role', 'unknown')
    time_str = msg.get('message_time', '')[11:19] if msg.get('message_time') else ''
    category = msg.get('category', '')

    context = msg.get('context', {})
    text = context.get('text', '') if isinstance(context, dict) else str(context)

    error_detail = msg.get('error_detail', '')
    send_results = msg.get('send_results', '')

    error_badge = ''
    if error_detail:
        error_badge = f'<span class="msg-error">ERROR: {esc(error_detail[:60])}</span>'
    elif send_results and send_results != '发送成功':
        error_badge = f'<span class="msg-error">SEND: {esc(send_results[:60])}</span>'

    return f"""
        <div class="message {role}">
            <div class="msg-time">{esc(time_str)}</div>
            <div class="msg-role {role}">{esc(role)}</div>
            <div class="msg-content">{esc(text[:500])}{error_badge}</div>
        </div>
    """


def format_conversation(conv_id, messages):
    """格式化单个会话为 HTML"""
    if not messages or not isinstance(messages, list):
        return f'<div class="no-data">会话 {conv_id[:16]}... 无消息数据</div>'

    msg_html = '\n'.join(format_message(msg) for msg in messages[:50])
    total = len(messages)
    shown = min(50, total)

    return f"""
        <div class="conversation-card">
            <div class="conversation-header">
                <div class="conversation-id">📞 会话 {esc(conv_id)}</div>
                <div>共 {total} 条消息（显示前 {shown} 条）</div>
            </div>
            <div class="message-list">
                {msg_html}
            </div>
        </div>
    """


def generate_analysis(data):
    """生成简单的根因分析摘要"""
    logs = data.get('logs', [])
    conversations = data.get('related_conversations', {}).get('conversations', {})

    error_logs = [l for l in logs if get_log_level(l) == 'ERROR']
    warning_logs = [l for l in logs if get_log_level(l) in ['WARNING', 'WARN']]

    analysis_html = []

    if not error_logs and not warning_logs:
        analysis_html.append("<h3>✅ 未检测到错误</h3>")
        analysis_html.append("<p>该时间段内没有 ERROR 或 WARNING 级别的日志。</p>")
    else:
        analysis_html.append(f"<h3>⚠️ 检测到 {len(error_logs)} 个错误 + {len(warning_logs)} 个警告</h3>")

        # 提取错误类型
        error_types = {}
        for log in error_logs[:10]:
            contents = log.get('contents', {})
            if isinstance(contents, dict):
                msg = str(contents.get('message', ''))[:200]
                # 尝试提取错误类型
                import re
                match = re.search(r'(\w+Error|\w+Exception)', msg)
                error_type = match.group(1) if match else '未知错误'
                error_types[error_type] = error_types.get(error_type, 0) + 1

        if error_types:
            analysis_html.append("<p><strong>错误类型分布:</strong></p><ul>")
            for err_type, count in sorted(error_types.items(), key=lambda x: -x[1]):
                analysis_html.append(f"<li><code>{esc(err_type)}</code>: {count} 次</li>")
            analysis_html.append("</ul>")

    # 关联会话
    if conversations:
        total_msgs = sum(len(msgs) if isinstance(msgs, list) else 0 for msgs in conversations.values())
        analysis_html.append(f"<p><strong>关联到 {len(conversations)} 个会话，共 {total_msgs} 条消息</strong></p>")

    analysis_html.append("""
        <p><strong>💡 建议后续操作:</strong></p>
        <ul>
            <li>使用页面顶部的搜索框过滤日志内容</li>
            <li>展开"完整 JSON 数据"查看所有字段</li>
            <li>结合 <code>cs-cli debug record &lt;record_id&gt;</code> 查询更详细的 trace</li>
        </ul>
    """)

    return '\n'.join(analysis_html)


def generate_report(input_json, output_html=None):
    """生成 HTML 报告"""
    # 读取输入
    if isinstance(input_json, str):
        with open(input_json, encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = input_json

    # 读取模板
    with open(TEMPLATE_PATH, encoding='utf-8') as f:
        template = f.read()

    # 统计
    logs = data.get('logs', [])
    error_count = sum(1 for l in logs if get_log_level(l) == 'ERROR')
    warning_count = sum(1 for l in logs if get_log_level(l) in ['WARNING', 'WARN'])
    conversations = data.get('related_conversations', {}).get('conversations', {})

    # 生成日志时间线
    log_entries_html = '\n'.join(format_log_entry(log) for log in logs)
    if not log_entries_html:
        log_entries_html = '<div class="no-data">该时间范围内没有日志数据</div>'

    # 生成关联会话
    conversations_html_parts = []
    for conv_id, messages in conversations.items():
        conversations_html_parts.append(format_conversation(conv_id, messages))
    conversations_html = '\n'.join(conversations_html_parts) or '<div class="no-data">未关联到会话消息</div>'

    # 生成分析
    analysis_html = generate_analysis(data)

    # 填充模板
    replacements = {
        '{{TITLE}}': f"RPA 日志分析 - {data.get('channel_name', '')} - {data.get('equipment_id', '')[:8]}",
        '{{CHANNEL_NAME}}': esc(data.get('channel_name', '')),
        '{{EQUIPMENT_ID}}': esc(data.get('equipment_id', '')),
        '{{QUERY_TIME}}': esc(data.get('query_time', '')),
        '{{RANGE_MINUTES}}': str(data.get('range_minutes', 10)),
        '{{TOTAL_LOGS}}': str(len(logs)),
        '{{ERROR_COUNT}}': str(error_count),
        '{{WARNING_COUNT}}': str(warning_count),
        '{{CONVERSATION_COUNT}}': str(len(conversations)),
        '{{LOG_ENTRIES}}': log_entries_html,
        '{{CONVERSATIONS}}': conversations_html,
        '{{ANALYSIS}}': analysis_html,
        '{{RAW_JSON}}': esc(json.dumps(data, ensure_ascii=False, indent=2, default=str)[:50000]),
        '{{GENERATED_AT}}': datetime.now(tz=CST).strftime('%Y-%m-%d %H:%M:%S')
    }

    html_content = template
    for key, value in replacements.items():
        html_content = html_content.replace(key, value)

    # 输出
    if output_html is None:
        equipment_short = data.get('equipment_id', 'unknown')[:8]
        channel = data.get('channel', 'unknown')
        output_html = f"rpa_log_report_{channel}_{equipment_short}.html"

    output_path = Path(output_html)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"✅ HTML 报告已生成: {output_path}")
    print(f"   总日志: {len(logs)} | 错误: {error_count} | 警告: {warning_count} | 关联会话: {len(conversations)}")
    return output_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description='RPA 日志 HTML 报告生成器')
    parser.add_argument('input', help='输入 JSON 文件路径（rpa_log_query.py 生成）')
    parser.add_argument('--output', '-o', help='输出 HTML 文件路径')

    args = parser.parse_args()

    generate_report(args.input, args.output)


if __name__ == '__main__':
    main()
