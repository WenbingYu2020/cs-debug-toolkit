#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest.py — 离线自检（无网络 / 无 AK / 不依赖 pytest）

用途：
  1. 新手安装后验证环境正确性：`csdbg selftest` 或 `python scripts/selftest.py`
  2. 构建质量门降级方案：pytest 不可用时由 build_*.ps1 调用

覆盖：模块导入（依赖齐备）→ RPA 记录规范化 → 四方证据包生成（含中文时间/错误汇总/
      心跳断流升级提示）→ 异常分类。全部离线，使用内嵌 mock 数据。
"""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

FAILED = []


def check(name, fn):
    try:
        fn()
        print(f"  ✅ {name}")
    except Exception as e:
        FAILED.append((name, e))
        print(f"  ❌ {name}: {e}")


def main() -> int:
    print("== cs-debug-toolkit 离线自检 ==")

    # ---- 1. 依赖与模块导入
    def t_import():
        import cross_analysis  # noqa: F401  （连带 server_log_query 的 aliyun SDK 依赖）
        import gap_analysis    # noqa: F401
        import host_events_query  # noqa: F401
    check("模块导入（含 aliyun-log-python-sdk 依赖）", t_import)
    if FAILED:
        print("\n❌ 自检中止：依赖缺失。请先执行 pip install -r requirements.txt")
        return 1

    import cross_analysis as ca
    import server_log_query as slq
    from datetime import datetime
    from exceptions import categorize_sls_error, AuthenticationError, DataSourceError

    # 基准时间戳：2026-09-23 14:40:00 北京时间（由时区换算，避免手写常量错误）
    T0 = int(datetime(2026, 9, 23, 14, 40, 0, tzinfo=ca.CST).timestamp())

    # ---- 2. RPA 记录规范化（北京时间展示）
    def t_normalize():
        recs = ca.normalize_rpa(
            [{'__time__': T0, 'level': 'INFO',
              'message': 'conv=deadbeefdeadbeefdeadbeefdeadbeef 测试消息'}], 'demo')
        assert len(recs) == 1, f"期望 1 条，得到 {len(recs)}"
        assert recs[0]['time'] == '2026-09-23 14:40:00', f"时间异常: {recs[0]['time']}"
        assert recs[0]['source'] == 'rpa:demo'
    check("RPA 记录规范化 + 北京时间展示", t_normalize)

    # ---- 3. 异常分类
    def t_exc():
        e = categorize_sls_error(Exception('Unauthorized: bad AccessKeyId'), 'selftest')
        assert isinstance(e, AuthenticationError) and e.recoverable is True
        e2 = categorize_sls_error(Exception('something odd'), 'selftest')
        assert isinstance(e2, DataSourceError)
    check("异常分类（认证识别 / 兜底归类）", t_exc)

    # ---- 4. 心跳断流检测 + 升级提示
    def t_gap():
        t0 = T0
        src = {'rpa:demo': [
            {'source': 'rpa:demo', 'ts': t0, 'time': '', 'level': 'INFO',
             'message': 'robot-health-report uptime=100', 'ids': {}},
            {'source': 'rpa:demo', 'ts': t0 + 600, 'time': '', 'level': 'INFO',
             'message': 'robot-health-report uptime=700', 'ids': {}},
        ]}
        hit = ca.detect_heartbeat_gap(src)
        assert hit and hit[0] == 600, f"应检出 600s 断流，得到 {hit}"
        hint = ca.build_host_upgrade_hint(src)
        assert '主机侧证据' in hint, "应生成第④源升级提示"
        assert ca.build_host_upgrade_hint({**src, 'host': [{'ts': 1}]}) == '', \
            "已有第④源时不应提示"
    check("心跳断流检测 + 第④源升级提示", t_gap)

    # ---- 4b. 故障签名知识库匹配
    def t_signatures():
        import fault_signatures as fsig
        kb = fsig.load_signatures()
        assert len(kb) >= 10, f"知识库条目过少: {len(kb)}"
        assert fsig.check_kb(kb) == [], "知识库校验未通过"
        hits = fsig.match_signatures({'server': [{
            'source': 'server', 'ts': T0, 'time': '', 'level': 'WARNING',
            'message': '跳过 WARNING 没有消息需要处理 running_state=running', 'ids': {}}]})
        assert any(h['id'] == 'stale-running-state' for h in hits), \
            f"应命中陈旧状态残留签名，得到 {[h['id'] for h in hits]}"
    check("故障签名知识库（加载/校验/匹配）", t_signatures)

    # ---- 5. 四方证据包端到端（mock 数据 → evidence.md）
    def t_evidence():
        t0 = T0
        sources = {
            'server': [{'source': 'server', 'ts': t0, 'time': '2026-09-23 14:40:00',
                        'level': 'WARNING',
                        'message': '跳过：没有消息需要处理 running_state=running',
                        'ids': {}}],
            'rpa:demo': [{'source': 'rpa:demo', 'ts': t0 + 1, 'time': '2026-09-23 14:40:01',
                          'level': 'INFO', 'message': '发送失败示例', 'ids': {}}],
            'ops': [{'source': 'ops', 'ts': t0 + 2, 'time': '2026-09-23 14:40:02',
                     'level': 'INFO', 'operator': 'selftest', 'remark': '配置变更示例',
                     'record_id': 'r1', 'path': 'agent/faq'}],
            'host': [{'source': 'host', 'host_kind': 'restart', 'host': 'demo-host',
                      'time': '2026-09-23 14:41:00', 'time_tz': 'Asia/Shanghai',
                      'ts': t0 + 60, 'level': 'INFO', 'message': '示例重启事件',
                      'ids': {}, 'host_source': 'sls', 'confidence': 'medium'}],
        }
        anchors = {'conversation_id': None, 'trace_id': None, 'request_id': None,
                   'dispatch_id': None, 'keyword': '示例'}
        meta = {'generated_at': '2026-09-23T14:42:00', 'start': '2026-09-23T14:30:00',
                'end': '2026-09-23T14:45:00', 'anchors': anchors,
                'source_stats': {k: len(v) for k, v in sources.items()},
                'host_bundle': '', 'host_events': '', 'host': 'demo-host',
                'host_summary': '', 'host_upgrade_hint': ''}
        import fault_signatures as fsig
        matrix = ca.anchor_hits(anchors, sources)
        cooccur = ca.id_cooccur(sources)
        anomalies = ca.extract_anomalies(sources)
        ops_flags = ca.correlate_ops(sources['server'], sources['rpa:demo'], sources['ops'])
        sig_hits = fsig.match_signatures(sources)
        md = ca.build_evidence_md(meta, sources, matrix, cooccur, anomalies, ops_flags,
                                  [DataSourceError('示例错误', source='selftest', recoverable=True)],
                                  sig_hits)
        for must in ('# 交叉分析证据包', '2026年09月23日', '锚点命中矩阵',
                     '多源合并时间线', '数据源错误汇总', '主机/IP 侧证据', '故障签名匹配'):
            assert must in md, f"evidence.md 缺少关键段落: {must}"
    check("四方证据包端到端生成（中文时间/错误汇总/主机专题/签名匹配）", t_evidence)

    # ---- 6. 时区统一
    def t_tz():
        assert ca.CST.utcoffset(None).total_seconds() == 8 * 3600
        dt = slq._parse_input_dt('2026-09-23T14:30:00')
        assert dt.tzinfo is not None and dt.hour == 14
    check("北京时间(UTC+8)统一处理", t_tz)

    print()
    if FAILED:
        print(f"❌ 自检未通过（{len(FAILED)} 项失败）")
        return 1
    print("✅ 自检全部通过 —— 工具链可用（依赖/规范化/异常/证据包/时区）")
    return 0


if __name__ == '__main__':
    sys.exit(main())
