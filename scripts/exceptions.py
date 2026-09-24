"""统一异常定义：四方数据源查询异常分类

使用方法：
    from exceptions import AuthenticationError, QuotaExceededError, TimeoutError
    
    try:
        result = query_sls(...)
    except AuthenticationError as e:
        # 引导用户检查 AK 配置
    except QuotaExceededError as e:
        # 提示配额不足，结果可能不完整
"""


class DataSourceError(Exception):
    """基类：数据源查询失败"""
    def __init__(self, message: str, source: str = None, recoverable: bool = False):
        super().__init__(message)
        self.source = source
        self.recoverable = recoverable


class AuthenticationError(DataSourceError):
    """认证失败：AK 无效/过期"""
    def __init__(self, message: str = "认证失败", source: str = None):
        super().__init__(message, source, recoverable=True)


class QuotaExceededError(DataSourceError):
    """配额耗尽：SLS 限流或日查询量达上限"""
    def __init__(self, message: str = "查询配额已用尽", source: str = None):
        super().__init__(message, source, recoverable=False)


class TimeoutError(DataSourceError):
    """超时：网络超时或查询响应超时"""
    def __init__(self, message: str = "查询超时", source: str = None):
        super().__init__(message, source, recoverable=True)


class ParseError(DataSourceError):
    """数据解析失败：返回格式异常"""
    def __init__(self, message: str = "响应解析失败", source: str = None):
        super().__init__(message, source, recoverable=False)


class NetworkError(DataSourceError):
    """网络错误：连接失败或网络不可达"""
    def __init__(self, message: str = "网络连接失败", source: str = None):
        super().__init__(message, source, recoverable=True)


def categorize_sls_error(exception: Exception, source: str) -> DataSourceError:
    """将 SLS SDK 异常转换为分类异常
    
    Args:
        exception: 原始异常（aliyun_log SDK 抛出的异常）
        source: 数据源标识（如 'server', 'rpa:qianniu'）
        
    Returns:
        分类后的 DataSourceError 子类实例
    """
    msg = str(exception).lower()
    
    # 认证相关
    if any(k in msg for k in ['unauthorized', 'accesskeyid', 'signature', 'accessdenied']):
        return AuthenticationError(f"SLS 认证失败: {exception}", source)
    
    # 配额相关
    if any(k in msg for k in ['quota', 'exceed', 'throttling', 'requestquotaexceeded']):
        return QuotaExceededError(f"SLS 查询配额不足: {exception}", source)
    
    # 超时相关
    if any(k in msg for k in ['timeout', 'timed out']):
        return TimeoutError(f"SLS 查询超时: {exception}", source)
    
    # 网络相关
    if any(k in msg for k in ['connect', 'network', 'unreachable', 'refused']):
        return NetworkError(f"SLS 网络连接失败: {exception}", source)
    
    # 其他
    return DataSourceError(f"SLS 查询失败: {exception}", source)


def categorize_cli_error(exception: Exception, source: str) -> DataSourceError:
    """将 cs-cli 调用异常转换为分类异常
    
    Args:
        exception: 原始异常（subprocess 或 JSON 解析异常）
        source: 数据源标识（通常为 'ops'）
        
    Returns:
        分类后的 DataSourceError 子类实例
    """
    msg = str(exception).lower()
    
    # 认证相关
    if any(k in msg for k in ['not logged in', 'auth', 'login', 'unauthorized']):
        return AuthenticationError(f"cs-cli 未登录: {exception}", source)
    
    # 超时相关
    if 'timeout' in msg:
        return TimeoutError(f"cs-cli 调用超时: {exception}", source)
    
    # JSON 解析
    if any(k in msg for k in ['json', 'decode', 'parse']):
        return ParseError(f"cs-cli 输出解析失败: {exception}", source)
    
    # 其他
    return DataSourceError(f"cs-cli 调用失败: {exception}", source)
