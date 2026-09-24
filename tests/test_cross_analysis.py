"""cross_analysis.py 核心纯函数单测（不依赖网络/AK）。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cross_analysis as ca  # noqa: E402


# ---------------------------------------------------------------- normalize_rpa
class TestNormalizeRpa:
    def test_extracts_ids_from_message(self):
        raw = [{
            "__time__": 1000,
            "message": "conv=dbc7a1d886834093b1a895cbb34551e0 task=abc12345abc12345 done",
            "level": "INFO",
        }]
        recs = ca.normalize_rpa(raw, "douyin")
        assert len(recs) == 1
        r = recs[0]
        assert r["source"] == "rpa:douyin"
        assert "dbc7a1d886834093b1a895cbb34551e0" in r["ids"]["conversation_id"]
        assert "abc12345abc12345" in r["ids"]["task_id"]

    def test_extra_conversation_id_field(self):
        raw = [{"__time__": "0", "message": "x", "extra_conversation_id": "feedface0000000000000000000000ab"}]
        r = ca.normalize_rpa(raw, "jingdong")[0]
        assert "feedface0000000000000000000000ab" in r["ids"]["conversation_id"]

    def test_hex_candidates_dedup(self):
        raw = [{"__time__": "0", "message": "abc12345abc12345abc12345abc12345 abc12345abc12345abc12345abc12345"}]
        r = ca.normalize_rpa(raw, "pdd")[0]
        assert r["ids"]["hex_candidates"] == ["abc12345abc12345abc12345abc12345"]


# ---------------------------------------------------------------- parse_host_time
class TestParseHostTime:
    @pytest.mark.parametrize("s,expected", [
        ("2026/09/18 10:30:00", "2026-09-18 10:30:00"),
        ("2026-09-18 10:30", "2026-09-18 10:30:00"),
        ("09/18/2026 10:30:00 AM", "2026-09-18 10:30:00"),
        ("2026-09-18T10:30:00", "2026-09-18 10:30:00"),
        ("", ""),
    ])
    def test_formats(self, s, expected):
        out, ts = ca.parse_host_time(s)
        assert out == expected
        if expected:
            assert ts > 0
        else:
            assert ts == 0

    def test_garbage_keeps_original_with_ts0(self):
        out, ts = ca.parse_host_time("garbage")
        assert out == "garbage"   # 解析不出时保留原文
        assert ts == 0


class TestHostLevel:
    def test_chinese_and_english_map(self):
        assert ca._host_level("错误") == "ERROR"
        assert ca._host_level("warning") == "WARNING"
        assert ca._host_level("信息") == "INFO"

    def test_unknown_upper(self):
        assert ca._host_level("verbose") == "VERBOSE"


# ---------------------------------------------------------------- anchor_hits
class TestAnchorHits:
    def test_hit_matrix(self):
        sources = {
            "server": [{"message": "conversation abc12345 done", "level": "INFO"}],
            "rpa:douyin": [{"message": "no match here"}],
        }
        m = ca.anchor_hits({"conversation_id": "abc12345"}, sources)
        assert m["conversation_id=abc12345"]["server"] == 1
        assert m["conversation_id=abc12345"]["rpa:douyin"] == 0

    def test_empty_anchor_skipped(self):
        m = ca.anchor_hits({"conversation_id": ""}, {"server": [{"message": "x"}]})
        assert m == {}

    def test_empty_sources(self):
        m = ca.anchor_hits({"kw": "x"}, {})
        assert m["kw=x"] == {}


# ---------------------------------------------------------------- id_cooccur / collect_ids
class TestIdCooccur:
    def test_only_cross_source_ids_kept(self):
        sources = {
            "server": [{"message": "x", "ids": {"conversation_id": ["aaa1111111111111", "only-server"]}}],
            "rpa:douyin": [{"message": "y", "ids": {"conversation_id": ["aaa1111111111111"]}}],
        }
        out = ca.id_cooccur(sources)
        assert "aaa1111111111111" in out
        assert "only-server" not in out
        assert out["aaa1111111111111"]["sources"] == {"server": 1, "rpa:douyin": 1}

    def test_hex_candidates_excluded(self):
        sources = {"server": [{"message": "x", "ids": {"hex_candidates": ["h" * 32]}}]}
        assert ca.id_cooccur(sources) == {}


# ---------------------------------------------------------------- extract_anomalies
class TestExtractAnomalies:
    def test_level_and_keyword(self):
        sources = {
            "server": [
                {"message": "ok", "level": "INFO"},
                {"message": "timeout waiting", "level": "INFO"},
                {"message": "boom", "level": "ERROR"},
            ]
        }
        bad = ca.extract_anomalies(sources)["server"]
        assert len(bad) == 2  # timeout 关键词 + ERROR 级别


# ---------------------------------------------------------------- host csv 解析
class TestHostCsv:
    def test_read_host_events_csv(self, tmp_path):
        csv_file = tmp_path / "01_system_power_boot.csv"
        csv_file.write_text(
            "Time,Id,Provider,Level,Message\n"
            "2026/09/18 10:30:00,6005,Microsoft-Windows-EventLog,信息,Event log started\n",
            encoding="utf-8-sig",
        )
        recs = ca._read_host_events_csv(csv_file, "power", "关机/开机/电源", "HOST-1")
        assert len(recs) == 1
        assert recs[0]["host_kind"] == "power"
        assert recs[0]["level"] == "INFO"
        assert recs[0]["host"] == "HOST-1"
        assert recs[0]["ts"] > 0
