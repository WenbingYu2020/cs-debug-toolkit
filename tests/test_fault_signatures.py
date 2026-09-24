"""故障签名知识库（P4-11）单测：加载/校验/匹配语义（全离线）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fault_signatures as fs  # noqa: E402


# ---------------------------------------------------------------- 知识库本体
class TestKnowledgeBase:
    def test_package_kb_loads(self):
        kb = fs.load_signatures()
        assert len(kb) >= 10, f"知识库条目过少: {len(kb)}"
        ids = [s['id'] for s in kb]
        assert len(ids) == len(set(ids)), "id 存在重复"

    def test_kb_valid(self):
        assert fs.check_kb(fs.load_signatures()) == []

    def test_reference_entries_excluded_from_matching(self):
        """evidence_pattern 为空的参考条目不参与自动匹配"""
        kb = fs.load_signatures()
        ref = [s for s in kb if not s.get('evidence_pattern')]
        assert ref, "应存在参考条目"
        assert fs.match_signatures({}, kb) == []


# ---------------------------------------------------------------- 匹配语义
def _server(msg, level='WARNING'):
    return {'source': 'server', 'ts': 1, 'time': '', 'level': level, 'message': msg, 'ids': {}}


class TestMatching:
    def test_stale_running_state_hit(self):
        sources = {'server': [_server('跳过 WARNING 没有消息需要处理, running_state=running')]}
        hits = fs.match_signatures(sources)
        assert any(h['id'] == 'stale-running-state' for h in hits)

    def test_sticky_takeover_hit(self):
        sources = {'server': [_server('payload has_manual_takeover:true skip')]}
        hits = fs.match_signatures(sources)
        assert any(h['id'] == 'sticky-manual-takeover' for h in hits)

    def test_no_hit_on_unrelated_records(self):
        sources = {'server': [_server('普通业务日志', level='INFO')]}
        assert fs.match_signatures(sources) == []

    def test_empty_session_requires_both_sources(self):
        """空会话签名需 RPA「空会话」+ server「会话无任何消息内容」同时命中"""
        only_server = {'server': [_server('会话无任何消息内容，多轮确认为空会话已关闭')]}
        assert not any(h['id'] == 'empty-session-giveup'
                       for h in fs.match_signatures(only_server))
        both = {
            'server': [_server('会话无任何消息内容，多轮确认为空会话已关闭')],
            'rpa:jingdong': [{'source': 'rpa:jingdong', 'ts': 2, 'time': '',
                              'level': 'INFO', 'message': '[UIA] 空会话 第 3/3 次确认', 'ids': {}}],
        }
        assert any(h['id'] == 'empty-session-giveup' for h in fs.match_signatures(both))

    def test_rpa_key_aggregates_all_channels(self):
        sources = {
            'rpa:douyin': [{'source': 'rpa:douyin', 'ts': 1, 'message': 'x', 'ids': {}}],
            'rpa:qianniu': [{'source': 'rpa:qianniu', 'ts': 2, 'message': 'y', 'ids': {}}],
        }
        recs = fs._source_records('rpa', sources)
        assert len(recs) == 2

    def test_max_count_zero_rule(self):
        """max_count=0 表示该源必须无记录"""
        rule = {'max_count': 0}
        ok, n = fs._check_rule(rule, [])
        assert ok and n == 0
        ok2, n2 = fs._check_rule(rule, ['[{"a":1}]'])
        assert not ok2 and n2 == 1

    def test_min_count_rule(self):
        rule = {'regex_all': ['route-to-a-live-agent'], 'min_count': 3}
        blobs = ['route-to-a-live-agent', 'route-to-a-live-agent']
        ok, n = fs._check_rule(rule, blobs)
        assert not ok and n == 2
        ok2, n2 = fs._check_rule(rule, blobs + ['route-to-a-live-agent'])
        assert ok2 and n2 == 3

    def test_match_result_shape(self):
        sources = {'server': [_server('跳过 WARNING 没有消息需要处理')]}
        hits = fs.match_signatures(sources)
        h = next(x for x in hits if x['id'] == 'stale-running-state')
        assert set(h) >= {'id', 'type', 'name', 'matched', 'conclusion_template'}
        assert h['matched'] == {'server': 1}
