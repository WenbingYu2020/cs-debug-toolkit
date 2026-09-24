"""host_events_query.py 核心纯函数单测（不依赖网络/AK）。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import host_events_query as heq  # noqa: E402


# ---------------------------------------------------------------- _parse_data
class TestParseData:
    def test_nested_data_field(self):
        r = {"data": '{"data": {"rpa_status": "online", "uptime_seconds": 100}}'}
        assert heq._parse_data(r) == {"rpa_status": "online", "uptime_seconds": 100}

    def test_flat_dict(self):
        r = {"data": '{"uptime_seconds": 5}'}
        assert heq._parse_data(r) == {"uptime_seconds": 5}

    def test_non_json(self):
        assert heq._parse_data({"data": "not-json"}) == {}
        assert heq._parse_data({}) == {}


# ---------------------------------------------------------------- resolve_identity
class TestResolveIdentity:
    def test_from_raw_records(self):
        recs = [{"hostname": "DESKTOP-ABC", "desktop_name": "客服-01",
                 "desktop_id": "ecd-123", "__tag__:__client_ip__": "1.2.3.4"}]
        ident = heq.resolve_identity(recs)
        assert ident["hostname"] == "DESKTOP-ABC"
        assert ident["ip"] == "1.2.3.4"

    def test_empty(self):
        assert heq.resolve_identity([]) == {}


# ---------------------------------------------------------------- _state_intervals
class TestStateIntervals:
    def test_state_changes(self):
        recs = [
            {"message": "robot-health-report", "__time__": "1000",
             "data": '{"data": {"rpa_status": "online", "client_status": "ok"}}'},
            {"message": "robot-health-report", "__time__": "1030",
             "data": '{"data": {"rpa_status": "offline", "client_status": "ok"}}'},
        ]
        iv = heq._state_intervals(recs)
        assert len(iv) == 2
        assert iv[0][0] == "online/ok" and iv[0][2] == 1030
        assert iv[1][0] == "offline/ok" and iv[1][2] is None


# ---------------------------------------------------------------- rebuild_sls_events
def _hb(ts, uptime, ver="1.0", mem=None, rpa="online", cli="ok"):
    data = {"rpa_status": rpa, "client_status": cli, "uptime_seconds": uptime}
    if mem is not None:
        data["memory_percent"] = mem
    return {"__time__": str(ts), "message": "robot-health-report",
            "app_version": ver, "data": json.dumps({"data": data})}


class TestRebuildSlsEvents:
    def test_no_heartbeat(self):
        ev = heq.rebuild_sls_events([], window_start=1000)
        assert len(ev) == 1 and ev[0]["host_kind"] == "power"

    def test_gap_without_uptime_reset_is_sleep(self):
        recs = [_hb(1000, 500), _hb(1000 + 400, 500)]  # 断流 400s >= 300，uptime 未回退
        ev = heq.rebuild_sls_events(recs, min_gap=300)
        kinds = [e["host_kind"] for e in ev]
        assert "power" in kinds

    def test_gap_with_uptime_reset_is_restart(self):
        recs = [_hb(1000, 500), _hb(1000 + 400, 30)]  # 断流 + uptime 回退 → 重启
        ev = heq.rebuild_sls_events(recs, min_gap=300)
        assert any(e["host_kind"] == "restart" for e in ev)

    def test_version_change_is_crash(self):
        recs = [_hb(1000, 500, ver="1.0"), _hb(1030, 500, ver="1.1")]  # 同开机内版本变化
        ev = heq.rebuild_sls_events(recs)
        assert any(e["host_kind"] == "crash" and "app_version" in e["message"] for e in ev)

    def test_rapid_restarts_is_crash_loop(self):
        # uptime 连续两次回退，间隔 <= 300s → 疑似崩溃循环
        recs = [_hb(1000, 500), _hb(1100, 100), _hb(1200, 80)]
        ev = heq.rebuild_sls_events(recs)
        assert any(e["host_kind"] == "crash" and "崩溃循环" in e["message"] for e in ev)

    def test_state_change(self):
        recs = [_hb(1000, 500, rpa="online"), _hb(1030, 500, rpa="offline")]
        ev = heq.rebuild_sls_events(recs)
        assert any(e["host_kind"] == "state" for e in ev)


# ---------------------------------------------------------------- parse_ecd_text
class TestParseEcdText:
    def test_id_line_format(self):
        text = (
            "# host-events.ps1 @ HOST1\n"
            "2026-09-18 10:35:12  ID=6005 [Microsoft-Windows-EventLog] 信息 Event log started\n"
        )
        recs = heq.parse_ecd_text(text, host="ecd-abc")
        assert len(recs) == 1
        assert recs[0]["host_kind"] == "restart"      # 6005 → restart
        assert recs[0]["host_source"] == "ecd"
        assert recs[0]["ts"] > 0

    def test_csv_line_format(self):
        text = '"2026/09/18 10:35:12","信息","42","Microsoft-Windows-Kernel-Power","The system is entering sleep."\n'
        recs = heq.parse_ecd_text(text, host="ecd-abc")
        assert len(recs) == 1
        assert recs[0]["host_kind"] == "power"        # 42 → power
        assert "entering sleep" in recs[0]["message"]

    def test_garbage_lines_skipped(self):
        recs = heq.parse_ecd_text("no timestamp here\n# comment\n")
        assert recs == []
