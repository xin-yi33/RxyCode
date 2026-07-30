"""
RxyCode 应用级日志模块（对标 opencode 日志模式）

- 结构化 key=value 格式
- 每次启动生成 8 字符 runID，附加到每条日志
- 日志路径：~/.rxycode/logs/rxycode.log（RotatingFileHandler，10MB x 5 轮转）
- FileHandler 始终开启，可选 stderr 输出
- 随进程退出自动关闭（atexit）

用法：
    from .log.logger import setup_logging, get_logger
    setup_logging(level="INFO", print_logs=False)
    logger = get_logger()
    logger.info("Something happened", extra={"port": 8765})
"""

import sys
import time
import uuid
import logging
import logging.handlers
import atexit
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Iterator

# 每次启动生成 8 字符 runID
RUN_ID = uuid.uuid4().hex[:8]
_CURRENT_RUN_ID: ContextVar[str | None] = ContextVar(
    "rxycode_current_run_id", default=None
)


def get_current_run_id() -> str:
    """Return the request/task run ID, or the process ID outside a run."""
    return _CURRENT_RUN_ID.get() or RUN_ID


def get_bound_run_id() -> str | None:
    """Return the request-scoped run ID without the process fallback."""
    return _CURRENT_RUN_ID.get()


def bind_run_id(run_id: str) -> Token:
    """Bind a run ID to the current async/thread context."""
    value = str(run_id).strip()
    if not value:
        raise ValueError("run_id must be non-empty")
    return _CURRENT_RUN_ID.set(value)


def reset_run_id(token: Token) -> None:
    """Restore the context that preceded :func:`bind_run_id`."""
    _CURRENT_RUN_ID.reset(token)


@contextmanager
def run_id_context(run_id: str | None = None) -> Iterator[str]:
    """Bind one run ID for the duration of a synchronous or async block."""
    value = str(run_id).strip() if run_id is not None else uuid.uuid4().hex
    token = bind_run_id(value)
    try:
        yield value
    finally:
        reset_run_id(token)

# 日志路径：~/.rxycode/logs/rxycode.log
LOG_DIR = Path.home() / ".rxycode" / "logs"
LOG_FILE = LOG_DIR / "rxycode.log"

_initialized = False
_logger_instance = None


class KeyValueFormatter(logging.Formatter):
    """key=value 结构化格式化器（对标 opencode 日志格式）"""

    def format(self, record: logging.LogRecord) -> str:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
        level = record.levelname
        msg = record.getMessage()

        # 基础行
        run_id = getattr(record, "run_id", None) or get_current_run_id()
        line = f"{ts} {level} run={run_id} message={_quote(msg)}"

        # extra 字段追加到行尾
        extras = []
        for key, value in record.__dict__.items():
            if key in (
                "name", "msg", "args", "created", "relativeCreated",
                "levelname", "levelno", "pathname", "filename", "module",
                "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                "msecs", "thread", "threadName", "processName", "process",
                "message", "taskName", "run_id",
            ):
                continue
            if key.startswith("_"):
                continue
            extras.append(f"{key}={_quote(str(value))}")

        if extras:
            line += " " + " ".join(extras)

        # 异常信息
        if record.exc_info and record.exc_info[1] is not None:
            line += "\n" + self.formatException(record.exc_info)

        return line


def _quote(value: str) -> str:
    """对含空格/引号/等号的值用双引号包裹，内部双引号转义"""
    if not value:
        return '""'
    needs_quote = any(c in value for c in ' "\n=\t')
    if needs_quote:
        return '"' + value.replace('"', '\\"') + '"'
    return value


def setup_logging(level: str = "INFO", print_logs: bool = False) -> logging.Logger:
    """
    初始化 RxyCode 日志系统。应在 cli() 启动时调用一次。

    Args:
        level: 日志级别 DEBUG / INFO / WARN / ERROR
        print_logs: 是否同时输出到 stderr（默认只写文件）

    Returns:
        配置好的 logger 实例
    """
    global _initialized, _logger_instance

    logger = logging.getLogger("rxycode")

    # 若已初始化且 FileHandler stream 仍然可用，直接返回
    if _initialized and _logger_instance is not None:
        fh = next((h for h in logger.handlers if isinstance(h, logging.FileHandler)), None)
        if fh and hasattr(fh, "stream") and not fh.stream.closed:
            return _logger_instance

    # 强制清除所有旧 handlers（避免 stale stream 问题）
    for h in list(logger.handlers):
        try:
            h.close()
        except Exception:
            pass
        logger.removeHandler(h)

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False  # 不传播到 root logger

    formatter = KeyValueFormatter()

    # 文件日志（始终开启，10MB x 5 轮转，避免单文件无限增长）
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            str(LOG_FILE), mode="a", maxBytes=10 * 1024 * 1024,
            backupCount=5, encoding="utf-8", errors="replace",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        atexit.register(file_handler.close)
    except Exception as e:
        # 日志初始化失败不应阻止应用启动
        print(f"[rxycode] Warning: failed to init file log: {e}", file=sys.stderr)

    # stderr 日志（可选）
    if print_logs:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.DEBUG)
        stderr_handler.setFormatter(formatter)
        logger.addHandler(stderr_handler)

    _initialized = True
    _logger_instance = logger
    return logger


def get_logger() -> logging.Logger:
    """获取 rxycode logger 实例。若尚未初始化则用默认配置初始化。"""
    global _logger_instance
    if _logger_instance is not None:
        return _logger_instance
    return setup_logging()
