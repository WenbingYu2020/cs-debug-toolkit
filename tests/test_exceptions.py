"""测试统一异常分类（P0 Issue #1）：
- 异常层级 recoverable 语义正确
- categorize_sls_error / categorize_cli_error 按错误文本正确归类
"""
import exceptions
from exceptions import (
    DataSourceError, AuthenticationError, QuotaExceededError,
    TimeoutError, ParseError, NetworkError,
    categorize_sls_error, categorize_cli_error,
)


class TestExceptionHierarchy:
    def test_all_subclasses_of_base(self):
        for cls in (AuthenticationError, QuotaExceededError, TimeoutError,
                    ParseError, NetworkError):
            assert issubclass(cls, DataSourceError)

    def test_recoverable_semantics(self):
        """可恢复类异常标记 recoverable=True，不可恢复类为 False"""
        assert AuthenticationError(source="x").recoverable is True
        assert TimeoutError(source="x").recoverable is True
        assert NetworkError(source="x").recoverable is True
        assert QuotaExceededError(source="x").recoverable is False
        assert ParseError(source="x").recoverable is False

    def test_source_attached(self):
        e = AuthenticationError(source="server")
        assert e.source == "server"

    def test_base_default_not_recoverable(self):
        assert DataSourceError("boom").recoverable is False
        assert DataSourceError("boom").source is None


class TestCategorizeSlsError:
    def test_auth(self):
        e = categorize_sls_error(Exception("Unauthorized: bad AccessKeyId"), "server")
        assert isinstance(e, AuthenticationError)
        assert e.source == "server"

    def test_signature(self):
        e = categorize_sls_error(Exception("SignatureDoesNotMatch"), "server")
        assert isinstance(e, AuthenticationError)

    def test_quota(self):
        e = categorize_sls_error(Exception("RequestQuotaExceeded"), "rpa:qianniu")
        assert isinstance(e, QuotaExceededError)
        assert e.recoverable is False

    def test_throttling(self):
        e = categorize_sls_error(Exception("Throttling: slow down"), "server")
        assert isinstance(e, QuotaExceededError)

    def test_timeout(self):
        e = categorize_sls_error(Exception("connection timed out"), "server")
        assert isinstance(e, TimeoutError)
        assert e.recoverable is True

    def test_network(self):
        e = categorize_sls_error(Exception("connection refused"), "server")
        assert isinstance(e, NetworkError)

    def test_fallback_generic(self):
        e = categorize_sls_error(Exception("something weird"), "server")
        assert type(e) is DataSourceError
        assert e.source == "server"


class TestCategorizeCliError:
    def test_not_logged_in(self):
        e = categorize_cli_error(Exception("user not logged in"), "ops")
        assert isinstance(e, AuthenticationError)

    def test_timeout(self):
        e = categorize_cli_error(Exception("subprocess timeout after 120s"), "ops")
        assert isinstance(e, TimeoutError)

    def test_json_parse(self):
        e = categorize_cli_error(Exception("JSON decode error"), "ops")
        assert isinstance(e, ParseError)
        assert e.recoverable is False

    def test_fallback_generic(self):
        e = categorize_cli_error(Exception("mysterious failure"), "ops")
        assert type(e) is DataSourceError
