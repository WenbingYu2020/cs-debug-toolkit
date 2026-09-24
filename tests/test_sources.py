"""数据源插件层（P4-10）单测：注册表 / QueryOutcome / 各源插件错误路径（全离线）"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sources  # noqa: E402
from exceptions import AuthenticationError  # noqa: E402


def _args(**kw):
    base = dict(
        start='2026-09-23T10:00:00', end='2026-09-23T11:00:00',
        conversation_id=None, trace_id=None, request_id=None, dispatch_id=None,
        query=None, level=None, limit=10, dev=False,
        workspace=None, agent=None, ops_limit=10,
        channel=None,
        host_bundle=None, host_events_equipment=None, host_events_desktop=None,
        host_events_min_gap=300, host_events_limit=100,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- 注册表
class TestBuildSources:
    def test_default_three_core_plugins(self):
        plugins = sources.build_sources(_args())
        assert [p.name for p in plugins] == ['server', 'rpa', 'ops']
        assert all(p.order < 40 for p in plugins)

    def test_host_bundle_adds_plugin(self):
        plugins = sources.build_sources(_args(host_bundle='x.zip'))
        assert [p.name for p in plugins] == ['server', 'rpa', 'ops', 'host-bundle']
        assert plugins[-1].order >= 40

    def test_host_events_adds_plugin(self):
        plugins = sources.build_sources(_args(host_events_equipment='eq-1'))
        assert plugins[-1].name == 'host-events'

    def test_both_host_plugins_sorted(self):
        plugins = sources.build_sources(_args(host_bundle='x.zip', host_events_desktop='d-1'))
        assert [p.name for p in plugins] == ['server', 'rpa', 'ops', 'host-bundle', 'host-events']


class TestQueryOutcome:
    def test_defaults(self):
        oc = sources.QueryOutcome(name='demo')
        assert oc.entries == [] and oc.files == [] and oc.errors == [] and oc.log == []
        assert oc.merge == 'replace'


# ---------------------------------------------------------------- 插件错误路径
class TestServerPlugin:
    def test_auth_error_categorized(self, monkeypatch):
        class _Boom:
            def __init__(self, *a, **kw): pass
            def query(self, **kw): raise RuntimeError('Unauthorized: bad AccessKeyId')

        monkeypatch.setattr(sources, 'ServerLogQuery', _Boom)
        oc = sources.ServerLogSource().run_query(_args(), Path('.'))
        assert len(oc.errors) == 1 and isinstance(oc.errors[0], AuthenticationError)
        assert oc.entries == [('server', [])]
        assert any('服务端查询失败' in line for line in oc.log)


class TestRpaPlugin:
    def test_channel_parallel_and_channel_error(self, monkeypatch):
        class _FakeRPA:
            def __init__(self, *a, **kw):
                self.config = {'channels': {'douyin': {}, 'jingdong': {}}}
            def query(self, channel=None, **kw):
                if channel == 'jingdong':
                    raise RuntimeError('boom')
                return [{'__time__': 0, 'message': 'conv=deadbeefdeadbeefdeadbeefdeadbeef',
                         'level': 'INFO'}]

        monkeypatch.setattr(sources, 'RPALogQuery', _FakeRPA)
        oc = sources.RPALogSource().run_query(_args(), Path('.'))
        keys = [k for k, _ in oc.entries]
        assert 'rpa:douyin' in keys and 'rpa:jingdong' not in keys
        assert any(e.source == 'rpa-log:jingdong' for e in oc.errors)
        assert ('rpa_douyin.json', oc.entries[0][1]) in oc.files
        assert any('✅ [2/4] RPA 端' in line for line in oc.log)


class TestOpsPlugin:
    def test_conversation_filter(self, monkeypatch):
        monkeypatch.setattr(sources.ops_log_query, 'list_records', lambda **kw: [
            {'record_id': 'r1', 'remark': 'conv abc 相关变更'},
            {'record_id': 'r2', 'remark': '无关记录'},
        ])
        oc = sources.OpsSource().run_query(_args(conversation_id='abc'), Path('.'))
        recs = dict(oc.entries)['ops']
        assert [r['record_id'] for r in recs] == ['r1']


class TestHostPlugin:
    def test_bundle_merge_flag_and_meta(self, monkeypatch):
        monkeypatch.setattr(sources, 'load_host_bundle',
                            lambda bundle, out_dir: ([{'ts': 1, 'host_kind': 'power',
                                                       'message': 'm', 'host': 'h1'}], 'sum', 'h1'))
        oc = sources.HostBundleSource().run_query(_args(host_bundle='x'), Path('.'))
        assert oc.merge == 'host-merge'
        assert oc.meta == {'host': 'h1', 'summary': 'sum'}

    def test_bundle_missing_file_categorized(self):
        oc = sources.HostBundleSource().run_query(_args(host_bundle='no-such-file.zip'), Path('.'))
        assert len(oc.errors) == 1
        assert any('主机侧证据载入失败' in line for line in oc.log)
