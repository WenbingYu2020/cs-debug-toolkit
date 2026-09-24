"""rpa_log_query.py 的查询逻辑单测：翻页 / quiet / 查询串转义。
用注入的假 aliyun SDK + 假 channels.json，不发起真实请求。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from rpa_log_query import RPALogQuery  # noqa: E402


class FakeLogItem:
    def __init__(self, t, contents):
        self._t = t
        self.contents = contents

    def get_time(self):
        return self._t

    def get_contents(self):
        return self.contents


class FakeResponse:
    def __init__(self, items):
        self._items = items

    def get_logs(self):
        return self._items


def _make_query(tmp_path):
    cfg = tmp_path / "channels.json"
    cfg.write_text(json.dumps({
        "endpoint": "cn-hangzhou.log.aliyuncs.com",
        "access_key_id": "test", "access_key_secret": "test",
        "rpa_project": "p", "server_project": "s",
        "channels": {"douyin": {"name": "抖音", "logstore": "ls-dy",
                                "dev_logstore": "ls-dy-dev"}},
    }), encoding="utf-8")
    return RPALogQuery(str(cfg))


class TestQueryPagination:
    def test_paginates_until_limit(self, tmp_path, monkeypatch):
        # limit > 每页 100 → 翻页取满；第三页不足一页则停止
        q = _make_query(tmp_path)
        pages = {
            0: FakeResponse([FakeLogItem(1000 + i, {"message": f"a{i}"}) for i in range(100)]),
            100: FakeResponse([FakeLogItem(1100 + i, {"message": f"b{i}"}) for i in range(100)]),
            200: FakeResponse([FakeLogItem(1200 + i, {"message": f"c{i}"}) for i in range(50)]),
            250: FakeResponse([]),
        }
        seen = []

        def fake_get_logs(request):
            seen.append(request.offset)
            return pages[request.offset]

        monkeypatch.setattr(q.client, "get_logs", fake_get_logs)
        out = q.query("douyin", "2026-09-18T10:00:00", "2026-09-18T11:00:00", limit=250, quiet=True)
        assert len(out) == 250
        assert seen == [0, 100, 200]  # 前两页满 100，第三页 50 条（<100 停止）

    def test_single_page_short(self, tmp_path, monkeypatch):
        q = _make_query(tmp_path)
        monkeypatch.setattr(q.client, "get_logs",
                            lambda req: FakeResponse([FakeLogItem(1, {"message": "x"})]))
        out = q.query("douyin", "2026-09-18T10:00:00", "2026-09-18T11:00:00", limit=10, quiet=True)
        assert len(out) == 1


class TestQueryQuiet:
    def test_quiet_suppresses_output(self, tmp_path, monkeypatch, capsys):
        q = _make_query(tmp_path)
        monkeypatch.setattr(q.client, "get_logs", lambda req: FakeResponse([]))
        q.query("douyin", "2026-09-18T10:00:00", "2026-09-18T11:00:00", quiet=True)
        captured = capsys.readouterr()
        assert "查询参数" not in captured.out

    def test_non_quiet_prints_params(self, tmp_path, monkeypatch, capsys):
        q = _make_query(tmp_path)
        monkeypatch.setattr(q.client, "get_logs", lambda req: FakeResponse([]))
        q.query("douyin", "2026-09-18T10:00:00", "2026-09-18T11:00:00", quiet=False)
        captured = capsys.readouterr()
        assert "查询参数" in captured.out


class TestQueryEscaping:
    def test_quotes_and_backslashes_escaped(self, tmp_path, monkeypatch):
        q = _make_query(tmp_path)
        captured = {}

        def fake_get_logs(request):
            captured["query"] = request.query
            return FakeResponse([])

        monkeypatch.setattr(q.client, "get_logs", fake_get_logs)
        q.query("douyin", "2026-09-18T10:00:00", "2026-09-18T11:00:00",
                conversation_id='abc"def\\ghi', quiet=True)
        # 原始引号被转义为 \"，反斜杠被双写
        assert 'abc\\"def\\\\ghi' in captured["query"]

    def test_unknown_channel_raises(self, tmp_path):
        q = _make_query(tmp_path)
        with pytest.raises(ValueError, match="未知渠道"):
            q.query("not-a-channel", "2026-09-18T10:00:00", "2026-09-18T11:00:00", quiet=True)
