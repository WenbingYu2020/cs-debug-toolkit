"""测试时区统一行为（P2 Issue #5）：
所有时间戳解析/展示统一按北京时间(UTC+8)，保证在任意时区主机上结果一致。
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# conftest.py 已注入假 SDK 并加 scripts/ 到 path
import server_log_query
import rpa_log_query
import cross_analysis
import ops_log_query
import host_events_query
import gap_analysis


CST = timezone(timedelta(hours=8))


class TestServerLogQuery:
    def test_parse_input_dt_naive_treated_as_beijing(self):
        """naive ISO 时间按北京时间解释"""
        dt = server_log_query._parse_input_dt("2026-09-23T14:30:00")
        assert dt.tzinfo == CST
        assert dt.hour == 14

    def test_parse_input_dt_aware_preserved(self):
        """带时区偏移的输入原样尊重"""
        dt = server_log_query._parse_input_dt("2026-09-23T14:30:00+09:00")
        assert dt.tzinfo == timezone(timedelta(hours=9))
        assert dt.hour == 14


class TestRpaLogQuery:
    def test_parse_input_dt_naive_treated_as_beijing(self):
        dt = rpa_log_query._parse_input_dt("2026-09-23T14:30:00")
        assert dt.tzinfo == CST
        assert dt.hour == 14

    def test_parse_input_dt_aware_preserved(self):
        dt = rpa_log_query._parse_input_dt("2026-09-23T14:30:00+00:00")
        assert dt.tzinfo == timezone.utc
        assert dt.hour == 14


class TestCrossAnalysis:
    def test_cst_constant(self):
        """CST 常量定义为 UTC+8"""
        assert cross_analysis.CST == CST

    def test_normalize_rpa_timestamp_display_uses_beijing(self):
        """RPA 日志规范化时，Unix 时间戳按北京时间展示（JSON 原始数据保持 ISO 格式）"""
        # 2026-09-23 14:30:00 Beijing = 1758614400 Unix (假设)
        # 实际用已知时间戳验证
        ts = datetime(2026, 9, 23, 14, 30, 0, tzinfo=CST).timestamp()
        raw = [{"__time__": int(ts), "level": "INFO", "message": "test"}]
        normalized = cross_analysis.normalize_rpa(raw, "test_channel")
        assert len(normalized) == 1
        # 原始 JSON 数据保持 ISO 格式（机器可解析）
        assert normalized[0]["time"] == "2026-09-23 14:30:00"


class TestChineseTimeFormat:
    """报告展示层中文时间格式化（原始 JSON 保持 ISO，仅 evidence.md 展示中文）"""

    def test_iso_space_format(self):
        assert cross_analysis._fmt_time_cn("2026-09-23 14:30:00") == "2026年09月23日 14:30:00"

    def test_iso_t_format(self):
        assert cross_analysis._fmt_time_cn("2026-09-23T14:30:00") == "2026年09月23日 14:30:00"

    def test_iso_with_timezone_suffix(self):
        """带时区后缀的 ISO 时间取前19位转中文"""
        assert cross_analysis._fmt_time_cn("2026-09-23T14:30:00+08:00") == "2026年09月23日 14:30:00"

    def test_empty_returns_empty(self):
        assert cross_analysis._fmt_time_cn("") == ""

    def test_date_only_kept_as_is(self):
        """无时分秒的异常格式保持原样"""
        assert cross_analysis._fmt_time_cn("2026-09-23") == "2026-09-23"

    def test_garbage_kept_as_is(self):
        """无法解析的输入返回原文"""
        assert cross_analysis._fmt_time_cn("not-a-date") == "not-a-date"


class TestOpsLogQuery:
    def test_parse_time_naive_as_beijing(self):
        """ops created_at 按北京时间解释"""
        dt = ops_log_query._parse_time("2026-09-23T14:30:00")
        assert dt.tzinfo == CST

    def test_as_cst_naive_attachment(self):
        """_as_cst 给 naive datetime 附加 CST"""
        dt_naive = datetime(2026, 9, 23, 14, 30)
        dt_aware = ops_log_query._as_cst(dt_naive)
        assert dt_aware.tzinfo == CST
        assert dt_aware.hour == 14

    def test_as_cst_already_aware_preserved(self):
        """already aware datetime 不改时区"""
        dt_utc = datetime(2026, 9, 23, 6, 30, tzinfo=timezone.utc)
        dt_result = ops_log_query._as_cst(dt_utc)
        assert dt_result.tzinfo == timezone.utc
        assert dt_result.hour == 6


class TestHostEventsQuery:
    def test_fmt_uses_beijing(self):
        """_fmt 把 Unix 时间戳按北京时间格式化"""
        ts = datetime(2026, 9, 23, 14, 30, 0, tzinfo=CST).timestamp()
        formatted = host_events_query._fmt(ts)
        assert formatted == "2026-09-23 14:30:00"

    def test_fmt_zero_returns_empty(self):
        assert host_events_query._fmt(0.0) == ""


class TestGapAnalysis:
    def test_ts_naive_as_beijing(self):
        """gap_analysis.ts() 按北京时间解释 naive ISO"""
        dt = gap_analysis.ts("2026-09-23T14:30:00")
        assert dt.tzinfo == CST
        assert dt.hour == 14

    def test_ts_aware_preserved(self):
        """带时区的输入保留原时区"""
        dt = gap_analysis.ts("2026-09-23T14:30:00+00:00")
        assert dt.tzinfo == timezone.utc
        assert dt.hour == 14
