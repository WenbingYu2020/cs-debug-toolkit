# -*- coding: utf-8 -*-
"""通用 SLS SQL 查询（LIKE 过滤）——绕过中文分词坑

背景：SLS 全文检索按 token 匹配，连续中文会整段成词（"失败" 搜不到 "登录执行失败"），
带下划线/点的串也会被切分。需要精确子串匹配时用本脚本的 SQL LIKE。

用法示例：
  # RPA 渠道日志（按设备 + 关键词）
  python sls_sql_query.py --channel douyin \
    --search '"<equipment_id>"' \
    --sql-where "message like '%登录方式%' or message like '%邮箱%'" \
    --start "2026-09-24T20:00:00" --end "2026-09-24T23:59:59" \
    --output out.json

  # 服务端日志
  python sls_sql_query.py --project bty-prod-ack-log --logstore customer-servhub-api \
    --search '"<equipment_id>"' --sql-where "1=1" --start ... --end ... 

说明：
- --search 是全文检索前置条件（如某个 ID 精确 token），默认 *（全量扫描，代价高）
- --sql-where 是 SQL where 子句，支持 like/and/or/field is not null 等
- 结果按 __time__ 排序输出；--output 保存原始 JSON（含全部字段）
- 配置默认读取脚本同目录 channels.json（或 --config 指定）
"""
import argparse
import datetime
import json
import os
import sys

from aliyun.log import LogClient, GetLogsRequest


def main():
    ap = argparse.ArgumentParser(description='通用 SLS SQL 查询（LIKE 过滤，绕开中文分词）')
    ap.add_argument('--config', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'channels.json'))
    ap.add_argument('--channel', help='渠道名（与 --project/--logstore 二选一，如 douyin/pinduoduo/jingdong/qianniu）')
    ap.add_argument('--project', help='SLS project（自定义查询时使用）')
    ap.add_argument('--logstore', help='SLS logstore（自定义查询时使用）')
    ap.add_argument('--search', default='*', help='全文检索前置条件，默认 *')
    ap.add_argument('--sql-where', required=True, help="SQL where 子句，如 message like '%%登录%%'")
    ap.add_argument('--start', required=True, help='开始时间 ISO 8601')
    ap.add_argument('--end', required=True, help='结束时间 ISO 8601')
    ap.add_argument('--limit', type=int, default=1000, help='最大返回条数（默认 1000）')
    ap.add_argument('--output', help='保存 JSON 文件路径；缺省则打印时间线')
    ap.add_argument('--config-note', action='store_true')
    args = ap.parse_args()

    if not os.path.exists(args.config):
        print(f'❌ 找不到配置文件: {args.config}', file=sys.stderr)
        sys.exit(1)
    cfg = json.load(open(args.config, encoding='utf-8'))

    if args.channel:
        if args.channel not in cfg.get('channels', {}):
            print(f"❌ 未知渠道: {args.channel}，支持: {list(cfg.get('channels', {}).keys())}", file=sys.stderr)
            sys.exit(1)
        project = cfg.get('project') or cfg.get('rpa_project')
        logstore = cfg['channels'][args.channel]['logstore']
    elif args.project and args.logstore:
        project, logstore = args.project, args.logstore
    else:
        print('❌ 需要 --channel 或 --project + --logstore', file=sys.stderr)
        sys.exit(1)

    client = LogClient(cfg['endpoint'], cfg['access_key_id'], cfg['access_key_secret'])
    from_ts = int(datetime.datetime.fromisoformat(args.start).timestamp())
    to_ts = int(datetime.datetime.fromisoformat(args.end).timestamp())

    sql_base = f"{args.search} | select * where {args.sql_where}"
    print(f"SQL: {sql_base} limit N")
    logs = []
    offset = 0
    while len(logs) < args.limit:
        # SQL 查询不支持 offset 参数，用 limit offset,size 分页
        sql = f"{sql_base} limit {offset},100"
        req = GetLogsRequest(project, logstore, from_ts, to_ts, topic='', query=sql, line=100)
        try:
            resp = client.get_logs(req)
        except Exception as e:
            print(f'❌ 查询失败: {e}', file=sys.stderr)
            sys.exit(2)
        page = []
        for log in resp.get_logs():
            d = {'__time__': log.get_time()}
            d.update(log.get_contents())
            page.append(d)
        if not page:
            break
        logs.extend(page)
        offset += len(page)
    print(f"total: {len(logs)}")
    if len(logs) >= args.limit:
        print(f"⚠️ 达到 limit={args.limit}，疑似截断：请缩小时间窗或提高 --limit")

    if args.output:
        json.dump(logs, open(args.output, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f"saved: {args.output}")
    else:
        for e in sorted(logs, key=lambda x: x['__time__']):
            t = datetime.datetime.fromtimestamp(e['__time__'])
            print(f"{t:%Y-%m-%d %H:%M:%S} [{e.get('level', '')}] "
                  f"{e.get('module', '')}.{e.get('function', '')} | {e.get('message', '')[:300]}")


if __name__ == '__main__':
    main()
