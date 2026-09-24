"""pytest 公共夹具：
1. 把 scripts/ 加入 sys.path，供测试直接 import 取证脚本；
2. 在 import 前注入假 aliyun SDK，保证测试不依赖真实 SDK 与网络/AK。
"""
import sys
import types
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


# ---- 假 aliyun SDK（仅用于让脚本 import 通过；真实 SLS 调用不测）
class _FakeLogClient:
    def __init__(self, *a, **kw):
        pass

    def get_logs(self, request):
        raise AssertionError("测试不得发起真实 SLS 请求，请使用返回固定数据的 fake")

    def list_logstore(self, project):
        raise AssertionError("测试不得发起真实 SLS 请求，请使用返回固定数据的 fake")


class _FakeGetLogsRequest:
    def __init__(self, *a, **kw):
        self.line = kw.get("line")
        self.offset = kw.get("offset")
        self.query = kw.get("query")


_aliyun = types.ModuleType("aliyun")
_log = types.ModuleType("aliyun.log")
_log.LogClient = _FakeLogClient
_log.GetLogsRequest = _FakeGetLogsRequest
_aliyun.log = _log
sys.modules["aliyun"] = _aliyun
sys.modules["aliyun.log"] = _log


def pytest_configure(config):
    """隔离 temp 输出：测试期间 CSDBG_TEMP 指向测试专用目录，避免污染真实 temp/。"""
    import os
    os.environ.setdefault("CSDBG_TEMP", str(SCRIPTS_DIR.parent / "tests" / ".test_temp"))
