import logging
import re

# SQLAlchemy 的异常字符串会携带完整绑定参数（[parameters: {...}]），
# 其中包含密码哈希、邮箱、学号等敏感数据；此前经 `logger.error(str(e))`
# 原样落盘 logs/app.log，形成凭据泄露。统一在日志层脱敏。
_PARAMS_RE = re.compile(r"\[parameters:.*", flags=re.S)
REDACTED = "[parameters: <redacted>]"


class SqlParamScrubber(logging.Filter):
    """把日志消息中的 [parameters: ...] 段落替换为占位符"""

    def filter(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if "[parameters:" in msg:
            record.msg = _PARAMS_RE.sub(REDACTED, msg)
            record.args = None
        return True
