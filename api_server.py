"""RxyCode API Server - FastAPI backend for the Ink TUI."""

import sys
import io
import asyncio
import concurrent.futures
import hmac
import ipaddress
import os
import re
import secrets
import threading
from contextlib import asynccontextmanager, suppress
from typing import Optional
from pathlib import Path

def _ensure_utf8_stdio():
    """Reconfigure stdout/stderr for UTF-8 on Windows.

    Called lazily from ``run_api_server()`` instead of at import time so
    that importing this module (e.g. in tests) does not clobber the
    streams pytest is capturing.
    """
    if sys.platform != "win32":
        return
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# Keep for backward compat – any external code that calls this at import
# time still works, but tests are not affected.
if sys.platform == "win32" and not hasattr(sys, "_called_from_test"):
    _ensure_utf8_stdio()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .log.log_helpers import (
    QUIET_PATHS,
    classify_agent_result,
    log_chat_request,
    log_chat_completed,
    log_chat_error,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, SecretStr, field_validator
import json as _json
import asyncio as _asyncio
import time as _time
import uuid as _uuid

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await startup(_app)
    try:
        yield
    finally:
        await shutdown(_app)


app = FastAPI(title="RxyCode API", version="3.0.0", lifespan=_lifespan)

# 日志（复用 main.py 初始化的 logger）
import logging as _logging
_logger = _logging.getLogger("rxycode")

# A process-local bearer credential protects every mutating HTTP entry point.
# ``run_api_server`` rotates it for each server start; embedded callers can
# configure a freshly generated value before handing it to the local frontend.
_api_token = secrets.token_urlsafe(32)
_allow_remote_api = False


def configure_api_token(token: str | None = None) -> str:
    """Install and return a fresh API bearer token without logging it."""
    global _api_token
    _api_token = token or secrets.token_urlsafe(32)
    return _api_token


def get_api_token() -> str:
    """Return the in-process token for trusted launchers and test clients."""
    return _api_token


def _remote_api_opted_in() -> bool:
    return os.environ.get("RXYCODE_ALLOW_REMOTE_API", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _validate_remote_token(token: str | None) -> str:
    value = (token or "").strip()
    normalized = value.casefold()
    placeholder = any(
        marker in normalized
        for marker in ("replace-with", "change-me", "changeme", "example-token")
    )
    if len(value) < 32 or len(set(value)) < 10 or placeholder:
        raise RuntimeError(
            "Remote API access requires a preconfigured high-entropy "
            "RXYCODE_API_TOKEN of at least 32 characters"
        )
    return value


def configure_api_access(*, allow_remote: bool, token: str | None = None) -> str:
    """Configure the socket-peer policy and bearer credential atomically."""
    global _allow_remote_api
    if allow_remote:
        token = _validate_remote_token(token)
    _allow_remote_api = allow_remote
    return configure_api_token(token)


def _is_loopback_bind_host(host: str) -> bool:
    normalized = host.strip().strip("[]")
    if normalized.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


_SENSITIVE_KEYS = re.compile(
    r"(?:authorization|api[_-]?key|access[_-]?token|bearer|password|secret|token)",
    re.IGNORECASE,
)
from .core.run_lifecycle import RunLifecycle
from .memory.chat_storage import CHAT_MESSAGE_VERSION, CHAT_SCHEMA_VERSION
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_COMMON_API_KEY = re.compile(r"(?i)\b(?:sk|key|token)-[A-Za-z0-9._-]{6,}")


def _redact_sensitive(value, *, key: str = ""):
    """Recursively remove credentials from frontend and exception logging."""
    if _SENSITIVE_KEYS.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact_sensitive(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_sensitive(item) for item in value]
    if isinstance(value, str):
        result = value.replace(_api_token, "[REDACTED]") if _api_token else value
        result = _BEARER_VALUE.sub("Bearer [REDACTED]", result)
        return _COMMON_API_KEY.sub("[REDACTED]", result)
    return value


def _redact_explicit(value: object, *secrets_to_remove: str) -> str:
    result = str(value)
    for secret_value in secrets_to_remove:
        if secret_value:
            result = result.replace(secret_value, "[REDACTED]")
    return str(_redact_sensitive(result))


def _is_loopback_client(host: str | None) -> bool:
    if not host:
        return False
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

# FIX: CORS - allow localhost origins for Ink TUI and development
_allowed_origins = [
    "http://localhost:8765",
    "http://127.0.0.1:8765",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Backend Patterns: Global error handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    safe_error = _redact_sensitive(str(exc))
    _logger.error(
        f"Unhandled exception: {request.method} {request.url.path} error={safe_error}",
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"error": safe_error, "type": type(exc).__name__},
    )

# Backend Patterns: Request logging middleware
@app.middleware("http")
async def log_requests(request, call_next):
    import time
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    # 排除 /log 端点自身，避免日志递归
    if request.url.path != "/log":
        # #6: heartbeat/health endpoints (/status, /models) are polled constantly
        # by the TUI; downgrade them to DEBUG so they don't drown real events.
        log_func = _logger.debug if request.url.path in QUIET_PATHS else _logger.info
        log_func(f"HTTP {request.method} {request.url.path}", extra={
            "status": response.status_code,
            "duration": f"{duration:.3f}s",
        })
    return response


@app.middleware("http")
async def require_local_bearer(request: Request, call_next):
    """Reject remote clients and authenticate every request except CORS preflight."""
    client_host = request.client.host if request.client else None
    if not _is_loopback_client(client_host) and not _allow_remote_api:
        return JSONResponse(status_code=403, content={"detail": "Loopback access only"})

    if request.method != "OPTIONS":
        authorization = request.headers.get("authorization", "")
        scheme, _, credential = authorization.partition(" ")
        valid = (
            scheme.casefold() == "bearer"
            and bool(credential)
            and hmac.compare_digest(credential, _api_token)
        )
        if not valid:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid bearer token"},
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)



class ChatRequest(BaseModel):
    message: str
    mode: str = "build"
    session_id: str = "latest"

    @field_validator("session_id")
    @classmethod
    def validate_session(cls, value: str) -> str:
        from .memory.long_term import validate_session_id

        return validate_session_id(value)


class ApproveRequest(BaseModel):
    approval_id: str
    decision: str  # "approved" | "rejected" | "always_allow_level"


class QuestionResponseRequest(BaseModel):
    question_id: str
    answer: str | None = None
    cancelled: bool = False


class CommandRequest(BaseModel):
    command: str
    session_id: str = "latest"

    @field_validator("session_id")
    @classmethod
    def validate_session(cls, value: str) -> str:
        from .memory.long_term import validate_session_id

        return validate_session_id(value)


class ModelOnboardingRequest(BaseModel):
    provider_model_id: str
    nickname: str | None = None
    api_key: SecretStr
    base_url: str

    @field_validator("provider_model_id")
    @classmethod
    def validate_provider_model_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("provider_model_id must not be empty")
        return value

    @field_validator("nickname")
    @classmethod
    def normalize_nickname(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        return value or None

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("api_key must not be empty")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        from .config.model_manager import normalize_provider_base_url

        return normalize_provider_base_url(value, require_https=True)

class LogEntry(BaseModel):
    level: str = "INFO"
    message: str
    context: Optional[dict] = None


class ChatResponse(BaseModel):
    response: str
    tool_calls: Optional[list] = None
    thinking: Optional[str] = None
    error: Optional[str] = None


_state = {
    "agent": None,
    "tui_proxy": None,
    "chat_history": [],
    "chat_histories": {},
    "active_session_id": "latest",
    "mode": "build",
    "busy": False,  # Bug A: True while a /chat/stream run is in progress
    "queue_manager": None,
    "scheduler": None,
    "service_loop": None,
    "task_deadline_seconds": 0.0,
    "service_futures": set(),
    "service_tasks": set(),
    "init_task": None,
}

# 请求级锁，防止并发状态串扰
_chat_lock = _asyncio.Lock()
_api_run_lifecycle = RunLifecycle()
# FIX-B1: Thread lock for agent initialization (prevents double-init)
_init_lock = threading.Lock()


def _activate_session(agent, session_id: str) -> list[dict]:
    """Select one isolated agent memory and API chat-history namespace."""
    setter = getattr(agent, "set_session", None)
    if callable(setter):
        setter(session_id)
    histories = _state.setdefault("chat_histories", {})
    active_session_id = str(_state.get("active_session_id") or "latest")
    exposed_history = _state.setdefault("chat_history", [])

    # ``chat_history`` predates named sessions and remains a supported public
    # process-state alias.  A caller may replace that list directly, so fold it
    # back into the active namespace before selecting the requested session.
    histories[active_session_id] = exposed_history
    history = (
        exposed_history
        if session_id == active_session_id
        else histories.setdefault(session_id, [])
    )
    _state["chat_history"] = history
    _state["active_session_id"] = session_id
    return history


def _session_message(role: str, content: str, *, run_id: str, **metadata) -> dict:
    """Build one JSON-safe message in the persisted session protocol."""
    return {
        "version": CHAT_MESSAGE_VERSION,
        "id": metadata.pop("id", f"{run_id}-{role}-{_uuid.uuid4().hex[:10]}"),
        "role": role,
        "content": str(content),
        "timestamp": metadata.pop("timestamp", int(_time.time() * 1000)),
        "run_id": run_id,
        **metadata,
    }


def _thinking_cursor(agent) -> tuple[tuple[str, ...], str]:
    history = tuple(str(item) for item in getattr(agent, "_thinking_history", []))
    return history, str(getattr(agent, "_last_thinking", "") or "")


def _thinking_since(agent, cursor: tuple[tuple[str, ...], str]) -> str:
    previous_history, previous_last = cursor
    current_history = tuple(
        str(item) for item in getattr(agent, "_thinking_history", [])
    )
    if current_history[:len(previous_history)] == previous_history:
        new_history = current_history[len(previous_history):]
    else:
        new_history = current_history
    if new_history:
        return "\n".join(new_history)
    current_last = str(getattr(agent, "_last_thinking", "") or "")
    return current_last if current_last != previous_last else ""
_service_futures_lock = threading.Lock()


class APIProxyTUI:
    """Proxy TUI that captures output for the API."""

    def __init__(self):
        self._mode = "build"
        self._model_name = ""
        self._last_output = []
        self._tool_calls = []
        self._stats = {}
        self._expand_thinking = False
        self._thinking_content = []

    def set_thinking_expanded(self, expanded):
        self._expand_thinking = expanded

    def get_thinking_expanded(self):
        return self._expand_thinking

    def set_mode(self, mode): self._mode = mode
    def set_model(self, name): self._model_name = name
    def set_process_fn(self, fn): pass
    def set_cancel_fn(self, fn): pass
    def set_session_list_fn(self, fn): pass
    def set_model_list_fn(self, fn): pass
    def set_new_session_fn(self, fn): pass
    def set_busy(self, busy): pass

    def update_stats(self, **kwargs):
        self._stats.update(kwargs)

    def write(self, text, color=""):
        self._last_output.append(text)

    def write_user_input(self, text):
        pass

    def write_thought(self, elapsed):
        self._last_output.append(f"  + Thought: {elapsed:.1f}s")

    def write_plan(self, steps):
        self._last_output.append(f"  + Plan: {len(steps)} Steps")

    def write_step(self, num, total, desc):
        self._last_output.append(f"  {num}/{total} {desc}")

    def write_tool_call(self, name, args, call_id=None):
        call_id = str(call_id or _uuid.uuid4().hex)
        self._tool_calls.append({
            "id": call_id,
            "name": name,
            "args": args,
            "result": "",
            "status": "running",
        })
        self._last_output.append(f"    {name}({args})")
        return call_id

    def write_tool_result(self, result, status="success", call_id=None):
        running = [
            call for call in self._tool_calls if call.get("status") == "running"
        ]
        target = next(
            (call for call in running if call.get("id") == call_id),
            running[0] if call_id is None and len(running) == 1 else None,
        )
        if target is not None:
            target["result"] = result
            target["status"] = status
        self._last_output.append(f"    -> {result[:200]}")

    def write_error(self, msg):
        self._last_output.append(f"  x {msg}")

    def write_success(self, msg):
        self._last_output.append(f"  v {msg}")

    def write_info(self, msg):
        self._last_output.append(f"  {msg}")

    def write_progress(self, text):
        self._last_output.append(f"  {text}")

    def stream_token(self, tok):
        pass

    def write_warning(self, msg):
        self._last_output.append(f"  ! {msg}")

    def write_model_indicator(self, mode, model):
        self._last_output.append(f"  {mode} . {model}")

    def write_capability_list(self):
        pass

    def write_command_list(self):
        pass

    def write_chat_list(self, chats):
        pass

    def run(self):
        pass

    def exit(self):
        pass

    def get_and_clear(self):
        output = "\n".join(self._last_output)
        tool_calls = self._tool_calls.copy()
        self._last_output.clear()
        self._tool_calls.clear()
        return output, tool_calls


def _init_agent():
    """Initialize the agent lazily. Thread-safe via _init_lock."""
    with _init_lock:
        if _state["agent"] is not None:
            return
        _do_init()

def _do_init():
    """Actual agent initialization (called under _init_lock)."""
    import os
    # Set working directory to RxyCode project root
    _project_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(_project_root)

    from .config.settings import load_config
    from .utils.i18n import i18n

    cfg = load_config()
    lang = cfg.get("language", "zh")
    i18n.set_lang(lang)

    from .core.agent_v2 import AgentV2 as Agent
    _state["agent"] = Agent()
    # Preserve /thinking preference toggled during the (slow) agent constructor.
    prior_proxy = _state.get("tui_proxy")
    prior_expand = bool(getattr(prior_proxy, "_expand_thinking", False)) if prior_proxy else False
    _state["tui_proxy"] = APIProxyTUI()
    _state["tui_proxy"].set_thinking_expanded(prior_expand)

    from .utils.tui import set_tui, get_tui
    set_tui(_state["tui_proxy"])

    model_name = _state["agent"].model_config.get("model_name", "unknown")
    _state["tui_proxy"].set_model(model_name)
    # #3: log the actually-resolved model once, so the log shows a real name
    # (e.g. deepseek-v4-flash) instead of the misleading startup "default".
    _logger.info("Agent initialized", extra={"model": model_name})


async def startup(_app: FastAPI | None = None):
    """Create one queue and scheduler service for this application lifespan."""
    # The app can be started more than once in tests or embedded runtimes.
    # Bind request serialization to the current lifespan's event loop and do
    # not reuse a lock left behind by an earlier loop.
    global _chat_lock
    _chat_lock = _asyncio.Lock()
    service_loop = _asyncio.get_running_loop()

    from .config.settings import get_data_dir, get_scheduler_config, load_config
    from .utils.queue import QueueManager

    cfg = load_config()
    scheduler_cfg = get_scheduler_config(cfg)
    deadline = max(
        0.0, float(scheduler_cfg.get("task_timeout_seconds", 0) or 0)
    )
    queue_manager = QueueManager(storage_path=get_data_dir() / "queue.json")

    scheduler = None
    if scheduler_cfg.get("enabled", True):
        from .scheduler.manager import TaskScheduler

        scheduler = TaskScheduler(
            storage_path=get_data_dir() / "scheduler_tasks.json",
            check_interval=float(scheduler_cfg.get("check_interval", 30) or 30),
        )
        scheduler.set_callback(_run_scheduled_prompt)

    _state.update(
        {
            "queue_manager": queue_manager,
            "scheduler": scheduler,
            "service_loop": service_loop,
            "task_deadline_seconds": deadline,
            "service_futures": set(),
            "service_tasks": set(),
        }
    )
    target_app = _app or app
    target_app.state.queue_manager = queue_manager
    target_app.state.scheduler = scheduler
    target_app.state.task_deadline_seconds = deadline

    interaction_timeout = float(
        (cfg.get("safety") or {}).get("approval_timeout", 120)
    )

    # 阶段二: API mode uses the SSE approval broker (fail-closed, 120s
    # default timeout from config safety.approval_timeout).
    try:
        from .core.safety.approval import (
            SseApproval,
            get_approval_broker,
            set_approval_broker,
        )
        _state["previous_approval_broker"] = get_approval_broker()
        set_approval_broker(SseApproval(timeout=interaction_timeout))
    except Exception:
        pass

    # User questions carry answers, not security decisions.  Keep their
    # lifecycle and pending registry separate from the safety approval broker.
    try:
        from .core.question import (
            SseQuestionBroker,
            get_question_broker,
            set_question_broker,
        )

        _state["previous_question_broker"] = get_question_broker()
        question_timeout = float(
            (cfg.get("safety") or {}).get("question_timeout", interaction_timeout)
        )
        set_question_broker(SseQuestionBroker(timeout=question_timeout))
    except Exception:
        pass

    async def _bg_init():
        try:
            await _asyncio.to_thread(_init_agent)
        except Exception as e:
            print(f"Warning: Agent init failed: {e}")

    _state["init_task"] = _asyncio.create_task(_bg_init())
    if scheduler is not None:
        scheduler.start()


async def shutdown(_app: FastAPI | None = None) -> None:
    """Stop lifespan services and join every submitted background operation."""
    scheduler = _state.get("scheduler")
    with _service_futures_lock:
        futures = list(_state.get("service_futures") or ())
    for future in futures:
        future.cancel()

    service_tasks = list(_state.get("service_tasks") or ())
    for task in service_tasks:
        task.cancel()
    if service_tasks:
        await _asyncio.gather(*service_tasks, return_exceptions=True)

    if scheduler is not None:
        await _asyncio.to_thread(scheduler.stop)

    init_task = _state.get("init_task")
    if init_task is not None:
        with suppress(_asyncio.CancelledError):
            await init_task

    agent = _state.get("agent")
    close_mcp = getattr(agent, "close_mcp", None)
    if callable(close_mcp):
        await _asyncio.to_thread(close_mcp)

    try:
        from .core.safety.approval import set_approval_broker
        set_approval_broker(_state.pop("previous_approval_broker", None))
    except Exception:
        pass

    try:
        from .core.question import get_question_broker, set_question_broker

        question_broker = get_question_broker()
        if question_broker is not None:
            question_broker.cancel_all()
        set_question_broker(_state.pop("previous_question_broker", None))
    except Exception:
        pass

    _state.update(
        {
            "queue_manager": None,
            "scheduler": None,
            "service_loop": None,
            "service_futures": set(),
            "service_tasks": set(),
            "init_task": None,
        }
    )
    target_app = _app or app
    target_app.state.queue_manager = None
    target_app.state.scheduler = None


async def _run_service_prompt(
    prompt: str,
    source: str,
    *,
    acquire_lock: bool = True,
) -> str:
    """Run a queued/scheduled prompt on the shared API loop and agent."""
    if _state.get("agent") is None:
        await _asyncio.to_thread(_init_agent)
    agent = _state.get("agent")
    if agent is None:
        return "[error: agent is not initialized]"

    deadline = max(
        0.0, float(_state.get("task_deadline_seconds", 0) or 0)
    )
    async def execute_owned() -> str:
        _state["busy"] = True
        previous_stream_mode = getattr(agent, "_stream_mode", False)
        operation = None
        try:
            agent._stream_mode = False
            operation = _asyncio.create_task(agent.run(prompt, mode="build"))
            _state.setdefault("service_tasks", set()).add(operation)
            if deadline <= 0:
                return str(await operation)

            done, _ = await _asyncio.wait({operation}, timeout=deadline)
            if operation in done:
                return str(await operation)

            cancel = getattr(agent, "cancel", None)
            if callable(cancel):
                cancel()
            operation.cancel()
            with suppress(_asyncio.CancelledError):
                await operation
            return (
                f"[task_stall_timeout] {source} task exceeded "
                f"{deadline:g}s and was cancelled"
            )
        except _asyncio.CancelledError:
            cancel = getattr(agent, "cancel", None)
            if callable(cancel):
                cancel()
            if operation is not None and not operation.done():
                operation.cancel()
                with suppress(_asyncio.CancelledError):
                    await operation
            raise
        finally:
            if operation is not None:
                _state.setdefault("service_tasks", set()).discard(operation)
            agent._stream_mode = previous_stream_mode
            _state["busy"] = False

    if acquire_lock:
        async with _chat_lock:
            return await execute_owned()
    return await execute_owned()


def _run_scheduled_prompt(prompt: str, *, acquire_lock: bool = True) -> str:
    """Thread callback that submits scheduling work to the lifespan loop."""
    loop = _state.get("service_loop")
    if loop is None or not loop.is_running():
        return "[error: API task service is not running]"

    future = _asyncio.run_coroutine_threadsafe(
        _run_service_prompt(
            prompt, "scheduled", acquire_lock=acquire_lock
        ),
        loop,
    )
    with _service_futures_lock:
        _state.setdefault("service_futures", set()).add(future)
    try:
        return str(future.result())
    except concurrent.futures.CancelledError:
        return "[cancelled: scheduled task]"
    finally:
        with _service_futures_lock:
            _state.setdefault("service_futures", set()).discard(future)


@app.post("/approve")
async def approve(req: ApproveRequest):
    """Resolve a pending tool-approval request (阶段二 safety gate)."""
    from .core.safety.approval import get_approval_broker, SseApproval
    broker = get_approval_broker()
    if not isinstance(broker, SseApproval):
        raise HTTPException(status_code=409, detail="No SSE approval broker active")
    ok = broker.resolve(req.approval_id, req.decision)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown or expired approval_id: {req.approval_id}")
    return {"ok": True}


@app.post("/question/respond")
async def question_response(req: QuestionResponseRequest):
    """Resolve a user question with an option value, free text, or cancel."""
    from .core.question import SseQuestionBroker, get_question_broker

    broker = get_question_broker()
    if not isinstance(broker, SseQuestionBroker):
        raise HTTPException(status_code=409, detail="No SSE question broker active")
    if req.answer is None and not req.cancelled:
        raise HTTPException(
            status_code=422,
            detail="answer is required unless cancelled is true",
        )
    try:
        ok = broker.resolve(
            req.question_id,
            req.answer,
            cancelled=req.cancelled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown or expired question_id: {req.question_id}",
        )
    return {"ok": True}


@app.post("/log")
async def receive_frontend_log(entry: LogEntry):
    """接收前端日志，统一写入 rxycode.log"""
    import json
    safe_context = _redact_sensitive(entry.context or {})
    safe_message = _redact_sensitive(entry.message)
    ctx_str = " ".join(
        f"{k}={json.dumps(v)}" for k, v in safe_context.items()
    )
    full_msg = f"[frontend] {safe_message}" + (f" {ctx_str}" if ctx_str else "")
    log_func = getattr(_logger, entry.level.lower(), None)
    if log_func is None or not callable(log_func):
        log_func = _logger.info
    log_func(full_msg)
    return {"ok": True}


@app.get("/status")
async def get_status():
    from .utils.streaming import token_stats, _get_memory_info
    from .utils.i18n import i18n
    from .log.monitor import run_monitor

    mem_mb, mem_pct = _get_memory_info()
    model_name = "unknown"
    agent_runtime = None
    mode = _state.get("mode", "build")

    if _state["agent"]:
        model_name = _state["agent"].model_config.get("model_name", "unknown")
        status_getter = getattr(type(_state["agent"]), "runtime_status", None)
        if callable(status_getter):
            agent_runtime = _state["agent"].runtime_status()

    # "缓存" now reports the volume of prompt tokens served from the provider's
    # context cache (was always 0 because cache_size was never updated).
    cached = token_stats.cache_hit_tokens
    cache_disp = f"{cached/1000:.1f}K" if cached >= 1000 else str(cached)

    # billing is None when the active model has no pricing entry in config —
    # surface None instead of a wrong hard-coded price.
    billing = token_stats.billing_amount
    return {
        "memory_mb": round(mem_mb, 1),
        "memory_pct": round(mem_pct, 1),
        "billing": round(billing, 4) if billing is not None else None,
        "cache_size": cache_disp,
        "cache_rate": f"{token_stats.cache_hit_rate:.1f}%",
        "provider_cache": {
            "prompt_tokens": token_stats.prompt_tokens,
            "hit_tokens": token_stats.cache_hit_tokens,
            "hit_rate": round(token_stats.cache_hit_rate, 2),
        },
        "application_cache": token_stats.get_application_cache_stats(),
        "input_tokens": token_stats.input_tokens,
        "output_tokens": token_stats.output_tokens,
        "context_used": token_stats.context_used,
        "context_max": token_stats.context_max,
        "context_used_k": round(token_stats.context_used / 1000, 1) if token_stats.context_used > 0 else 0,
        "context_max_k": int(token_stats.context_max / 1000),
        "mode": mode,
        "model": model_name,
        "language": i18n.lang,
        "runs": run_monitor.snapshot(),
        "agent_runtime": agent_runtime,
        "active_run": {
            "busy": _api_run_lifecycle.busy,
            "kind": _api_run_lifecycle.active_kind,
        },
    }


@app.get("/models")
async def get_models():
    """Return structured model list for the model selection panel."""
    from .config.settings import load_config
    cfg = load_config()
    models = cfg.get("models", {})
    active = cfg.get("active_model", "")
    result = []
    for name, mcfg in models.items():
        result.append({
            "id": name,
            "name": mcfg.get("model_name", name),
            "nickname": name,
            "provider_model_id": mcfg.get("model_name", name),
            "base_url": mcfg.get("base_url", ""),
            "active": name == active,
        })
    return {"models": result, "active": active}


@app.post("/models/onboard", status_code=201)
async def onboard_model(req: ModelOnboardingRequest):
    """Probe credentials in memory and persist only a working model mapping."""
    from .config.model_manager import (
        add_model,
        list_models,
        probe_model_connection,
        remove_model,
        set_active_model,
    )

    provider_model_id = req.provider_model_id
    nickname = req.nickname or provider_model_id
    api_key = req.api_key.get_secret_value().strip()
    base_url = req.base_url

    if nickname in list_models():
        raise HTTPException(status_code=409, detail=f"Model nickname already exists: {nickname}")

    probe = await _asyncio.to_thread(
        probe_model_connection,
        api_key=api_key,
        base_url=base_url,
        provider_model_id=provider_model_id,
    )
    if not probe.get("success"):
        safe_error = _redact_explicit(
            probe.get("error", "Connection failed"), api_key
        )
        raise HTTPException(
            status_code=400,
            detail=f"Connection test failed; model was not saved: {safe_error}",
        )

    try:
        add_model(
            nickname,
            api_key,
            base_url,
            model_name=provider_model_id,
        )
        if not set_active_model(nickname):
            raise RuntimeError("saved model could not be activated")
    except Exception as exc:
        # The preflight is deliberately persistence-free. If the subsequent
        # write is only partly successful, roll it back before reporting.
        try:
            remove_model(nickname)
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save model: {_redact_explicit(exc, api_key)}",
        ) from exc

    return {
        "action": "model_added",
        "message": f"Model '{nickname}' added and connection tested successfully",
        "model": {
            "id": nickname,
            "nickname": nickname,
            "provider_model_id": provider_model_id,
            "base_url": base_url,
            "active": True,
        },
        "probe": {"elapsed": probe.get("elapsed")},
    }


@app.post("/chat")
async def chat(req: ChatRequest):
    if not _state["agent"]:
        try:
            _init_agent()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Agent not initialized: {e}")

    # Validate empty message
    if not req.message or not req.message.strip():
        return ChatResponse(response="", error="Empty message. Please provide a non-empty message.")

    # 添加请求级锁，防止并发状态串扰
    # Validate mode
    valid_modes = ("build", "plan", "compose")
    if req.mode not in valid_modes:
        return ChatResponse(response=f"Invalid mode: {req.mode}. Valid modes: {valid_modes}", error=f"Invalid mode: {req.mode}")

    async def run_chat() -> ChatResponse:
        async with _chat_lock:
            _state["mode"] = req.mode
            proxy = _state["tui_proxy"]
            proxy._last_output.clear()
            proxy._tool_calls.clear()
            from .utils.tui import set_tui, get_tui
            _prev_tui = get_tui()
            set_tui(proxy)
            agent = _state["agent"]
            history = _activate_session(agent, req.session_id)
            run_id = _uuid.uuid4().hex
            from .core.tracing import Tracer
            from .log.logger import run_id_context
            from .log.monitor import run_monitor
            previous_tracer = getattr(agent, "_tool_tracer", None)
            started_at = _time.monotonic()
            terminal_status = "failed"
            user_record = _session_message("user", req.message, run_id=run_id)
            history.append(user_record)

            with run_id_context(run_id):
                try:
                    agent._tool_tracer = Tracer(run_id=run_id)
                    thinking_cursor = _thinking_cursor(agent)
                    result = await agent.run(req.message, mode=req.mode)
                    terminal_status, _detail = classify_agent_result(result)
                    _output, tool_calls = proxy.get_and_clear()

                    thinking = _thinking_since(agent, thinking_cursor)
                    if thinking:
                        history.append(
                            _session_message(
                                "thinking", thinking, run_id=run_id, done=True, live=False
                            )
                        )
                    for tool_call in tool_calls:
                        tool_result = str(tool_call.get("result", ""))
                        history.append(
                            _session_message(
                                "tool",
                                tool_result,
                                run_id=run_id,
                                toolName=str(tool_call.get("name", "unknown")),
                                toolArgs=str(tool_call.get("args", "")),
                                toolStatus=str(tool_call.get("status", "success")),
                                toolStdout=tool_result,
                            )
                        )
                    history.append(
                        _session_message("assistant", result, run_id=run_id)
                    )

                    return ChatResponse(
                        response=result,
                        tool_calls=tool_calls if tool_calls else None,
                        thinking=thinking if thinking else None,
                    )
                except _asyncio.CancelledError:
                    terminal_status = "cancelled"
                    history.append(
                        _session_message("system", "Cancelled", run_id=run_id)
                    )
                    raise
                except Exception as e:
                    terminal_status = "failed"
                    history.append(
                        _session_message("system", f"Error: {e}", run_id=run_id)
                    )
                    return ChatResponse(response="", error=str(e))
                finally:
                    agent._tool_tracer = previous_tracer
                    set_tui(_prev_tui)
                    run_monitor.record(
                        run_id, terminal_status, _time.monotonic() - started_at
                    )

    try:
        return await _api_run_lifecycle.run(run_chat, kind="chat")
    except _asyncio.CancelledError:
        return ChatResponse(response="", error="Cancelled")


async def _execute_explicit_command_tool(name: str, args: dict) -> tuple[str, bool]:
    """Execute a literal slash command through the agent's safety gate."""
    if _state.get("agent") is None:
        await _asyncio.to_thread(_init_agent)
    agent = _state.get("agent")
    if agent is None:
        return "[error: agent is not initialized]", False
    try:
        result = str(await agent._execute_tool(
            name,
            args,
            approval_source="explicit_command",
            mode=_state.get("mode", "build"),
        ))
    except Exception as exc:
        return f"[error executing {name}: {exc}]", False
    status, _ = classify_agent_result(result)
    missing = result.strip().lower().startswith("[not found")
    return result, status == "succeeded" and not missing


async def _execute_command(req: CommandRequest):
    cmd = req.command.strip()
    parts = cmd.split(None, 1)
    c = parts[0].lower() if parts else ""
    args = parts[1] if len(parts) > 1 else ""
    agent = _state.get("agent")
    history = (
        _activate_session(agent, req.session_id)
        if agent is not None
        else _state.setdefault("chat_histories", {}).setdefault(req.session_id, [])
    )

    if c == "/exit":
        return {"action": "exit", "message": "再见！"}

    if c == "/clear":
        history.clear()
        from .utils.streaming import token_stats
        token_stats.reset()
        # Also clear agent memory to prevent stale context affecting next queries
        if agent is not None:
            resetter = getattr(agent, "reset_session", None)
            if callable(resetter):
                resetter()
            else:
                agent._memory.clear()
                agent._session_loaded = False
        return {"action": "cleared", "message": "已清除"}

    if c == "/models":
        from .config.settings import load_config
        cfg = load_config()
        models = cfg.get("models", {})
        active = cfg.get("active_model", "")
        lines = []
        for name, mcfg in models.items():
            status = " (active)" if name == active else ""
            lines.append(f"{name}{status} - {mcfg.get('model_name', '')} @ {mcfg.get('base_url', '')}")
        return {"action": "models", "message": "\n".join(lines) if lines else "No models configured"}

    if c == "/model" and args:
        from .config.settings import load_config, get_model_config
        from .config.model_manager import set_active_model
        cfg = load_config()
        if args in cfg.get("models", {}):
            set_active_model(args)
            active_agent = _state["agent"]
            switcher = getattr(type(active_agent), "switch_model", None)
            if callable(switcher):
                active_agent._cfg = load_config()
                active_agent.switch_model(args)
            else:
                active_agent.model_config = get_model_config(args, cfg)
            return {"action": "model_changed", "message": f"Model switched: {args}"}
        else:
            return {"action": "error", "message": f"Model not found: {args}"}

    if c == "/plan":
        _state["mode"] = "plan"
        return {"action": "mode_changed", "mode": "plan", "message": "已切换到 Plan 模式"}

    if c == "/build":
        _state["mode"] = "build"
        return {"action": "mode_changed", "mode": "build", "message": "已切换到 Build 模式"}

    if c == "/compose":
        _state["mode"] = "compose"
        return {"action": "mode_changed", "mode": "compose", "message": "已切换到 Compose 模式"}

    if c == "/mode":
        valid_modes = ["build", "plan", "compose"]
        if args and args.strip().lower() in valid_modes:
            new_mode = args.strip().lower()
            _state["mode"] = new_mode
            return {"action": "mode_changed", "mode": new_mode, "message": f"已切换到 {new_mode.capitalize()} 模式"}
        return {"action": "error", "message": f"Invalid mode: {args}. Valid: {', '.join(valid_modes)}"}

    if c == "/addmodel":
        if args:
            return {
                "action": "error",
                "message": "Credential-bearing /addmodel commands are disabled; use the add-model wizard.",
            }
        return {
            "action": "addmodel_start",
            "message": "开始添加模型流程",
            "steps": ["provider_model_id", "api_key", "api_url", "nickname"],
        }
    if c == "/addmodel-step":
        return {
            "action": "error",
            "message": "Legacy model-step commands are disabled; use the typed model onboarding endpoint.",
        }

    if c == "/language":
        from .config.settings import load_config, save_config
        from .utils.i18n import i18n
        lang = args.strip().lower()
        # Accept "/language english", "/language en", "/language-english", etc.
        if not lang:
            return {"action": "language_show", "message": f"当前语言: {i18n.lang}。用法: /language zh|en"}
        # Normalize aliases
        lang_map = {"english": "en", "en": "en", "chinese": "zh", "zh": "zh", "中文": "zh"}
        lang = lang_map.get(lang, lang)
        if lang not in ("zh", "en"):
            return {"action": "error", "message": f"不支持的语言: {args}。可选: zh, en"}
        cfg = load_config()
        cfg["language"] = lang
        save_config(cfg)
        i18n.set_lang(lang)
        if lang == "zh":
            return {"action": "language_switched", "language": lang, "message": "语言已切换到中文"}
        else:
            return {"action": "language_switched", "language": lang, "message": "Language switched to English"}

    if c == "/help":
        help_text = (
            "/help - 帮助\n"
            "/clear - 清除上下文\n"
            "/models - 列出模型\n"
            "/model <name> - 切换模型\n"
            "/addmodel - 打开安全模型接入向导（密钥不写入命令）\n"
            "/plan - 规划模式\n"
            "/build - 构建模式\n"
            "/compose - 编排模式\n"
            "/mode <build|plan|compose> - 切换模式\n"
            "/memory add|list|remove|search <args>\n"
            "/list-chats - 列出已保存的对话\n"
            "/save-chat - 保存当前对话\n"
            "/load-chat - 加载已保存的对话\n"
            "/queue - 任务队列管理\n"
            "/schedule - 定时任务管理\n"
            "/language zh|en - 切换界面语言\n"
            "/thinking - 展开/折叠思考过程\n"
            "/cache - 缓存统计\n"
            "/find-skill <name> - \u641c\u7d22\u5e76\u4e0b\u8f7d skill\n"
            "/addskill <name|url> - \u5b89\u88c5 skill\n"
            "/list-skills - \u5217\u51fa\u5df2\u5b89\u88c5\u7684 skills\n"
            "/remove-skill <name> - \u5220\u9664 skill\n"
            "/addmcp <name> <cmd> [args] - \u6dfb\u52a0 MCP \u670d\u52a1\n"
            "/list-mcp - \u5217\u51fa MCP \u670d\u52a1\n"
            "/remove-mcp <name> - \u5220\u9664 MCP \u670d\u52a1\n"
            "/exit - 退出\n"
        )
        return {"message": help_text}

    if c == "/session" or c == "/list-chats":
        from .memory.chat_storage import chat_storage
        from datetime import datetime as _dt
        chats = chat_storage.list_chats()
        if not chats:
            return {"action": "session_list", "message": "no sessions", "chats": []}
        chat_items = []
        for ch in chats:
            name = ch.get("name", "")
            preview = ch.get("preview", "")[:30]
            t = ch.get("time", 0)
            time_str = _dt.fromtimestamp(t).strftime("%m/%d %H:%M") if t else ""
            chat_items.append({"name": name, "preview": preview, "time": time_str})
        return {"action": "session_list", "chats": chat_items, "message": ""}

    if c == "/memory":
        sub = args.split(None, 1)
        subcmd = sub[0].lower() if sub else ""
        subargs = sub[1] if len(sub) > 1 else ""

        if subcmd == "add" and subargs:
            result, ok = await _execute_explicit_command_tool(
                "memory", {"operation": "add", "query": subargs, "limit": 10}
            )
            return {"action": "memory_add" if ok else "error", "message": result}
        elif subcmd == "list":
            result, ok = await _execute_explicit_command_tool(
                "memory", {"operation": "list", "query": "", "limit": 1000}
            )
            if not ok:
                return {"action": "error", "message": result}
            from .memory.user_memory import UserMemory
            entries = UserMemory().list_all()
            if not entries:
                return {"action": "memory_list", "message": result, "memories": []}
            return {"action": "memory_list", "message": result, "memories": entries}
        elif subcmd == "remove" and subargs:
            if not subargs.isdigit():
                return {"message": "ID must be a number"}
            result, ok = await _execute_explicit_command_tool(
                "memory", {"operation": "remove", "query": subargs, "limit": 10}
            )
            return {"action": "memory_remove" if ok else "error", "message": result}
        elif subcmd == "search" and subargs:
            result, ok = await _execute_explicit_command_tool(
                "memory", {"operation": "search", "query": subargs, "limit": 5}
            )
            return {"action": "memory_search" if ok else "error", "message": result}
        return {"message": "Usage: /memory add|list|remove|search <args>"}

    # Handle bare / or /help
    if c == "/" or c == "/help":
        help_text = (
            "/help - 帮助\n"
            "/clear - 清除上下文\n"
            "/models - 列出模型\n"
            "/model <name> - 切换模型\n"
            "/addmodel - 打开安全模型接入向导（密钥不写入命令）\n"
            "/plan - 规划模式\n"
            "/build - 构建模式\n"
            "/compose - 编排模式\n"
            "/memory add|list|remove|search <args>\n"
            "/list-chats - 列出已保存的对话\n"
            "/save-chat - 保存当前对话\n"
            "/load-chat - 加载已保存的对话\n"
            "/queue - 任务队列管理\n"
            "/schedule - 定时任务管理\n"
            "/language zh|en - 切换界面语言\n"
            "/thinking - 展开/折叠思考过程\n"
            "/cache - 缓存统计\n"
            "/exit - 退出\n"
        )
        return {"action": "help", "message": help_text}

    if c == "/thinking":
        # Safe before agent init: never block on _init_agent / never AttributeError
        # when tui_proxy is still None (startup race before first chat).
        proxy = _state.get("tui_proxy")
        if proxy is None:
            proxy = APIProxyTUI()
            _state["tui_proxy"] = proxy
        new_state = not bool(getattr(proxy, "_expand_thinking", False))
        proxy.set_thinking_expanded(new_state)
        # Also sync to the global TUI (could be StreamTUI during streaming).
        # StreamTUI.set_thinking_expanded(True) emits a reasoning snapshot SSE
        # from the session recorder so mid-run expand can catch up (U3).
        from .utils.tui import get_tui
        current_tui = get_tui()
        if current_tui and current_tui is not proxy:
            set_thinking = getattr(current_tui, "set_thinking_expanded", None)
            if set_thinking:
                set_thinking(new_state)
        return {"action": "thinking_toggled", "message": "思考过程: " + ("展开" if new_state else "折叠"), "expanded": new_state}

    if c == "/cache":
        # 处理子命令
        cache_args = args.strip().lower()

        if cache_args == "clear":
            from .cache.precise_cache import precise_cache
            from .cache.semantic_cache import semantic_cache
            precise_cache.clear()
            semantic_cache.clear()
            return {"action": "cache_cleared", "message": "Cache cleared successfully"}

        if cache_args == "clean":
            from .cache.precise_cache import precise_cache
            from .cache.semantic_cache import semantic_cache
            precise_expired = precise_cache.clean_expired()
            semantic_expired = semantic_cache.clean_expired()
            return {"action": "cache_cleaned", "message": f"Cleaned {precise_expired + semantic_expired} expired entries"}

        # 原有的统计逻辑
        from .cache.precise_cache import precise_cache
        from .cache.semantic_cache import semantic_cache
        from .utils.streaming import token_stats
        pstats = precise_cache.get_stats()
        sstats = semantic_cache.get_stats()
        app_stats = token_stats.get_application_cache_stats()
        precise_session = app_stats["precise"]
        semantic_session = app_stats["semantic"]
        lines = [
            "",
            "  Cache Statistics:",
            "  --- Precise (exact match) ---",
            f"    Entries: {pstats['total_entries']} (active: {pstats['active_entries']}, expired: {pstats['expired_entries']})",
            f"    Total hits: {pstats['total_hits']}",
            f"    Session: {precise_session['hits']} hit / {precise_session['misses']} miss / {precise_session['bypassed']} bypass",
            f"    Eligible hit rate: {precise_session['hit_rate']:.1f}% (eligible: {precise_session['eligibility_rate']:.1f}%, bypass: {precise_session['bypass_rate']:.1f}%)",
            "  --- Semantic (similar match) ---",
            f"    Entries: {sstats['total_entries']} (active: {sstats['active_entries']}, expired: {sstats['expired_entries']})",
            f"    Total hits: {sstats['total_hits']}",
            f"    Session: {semantic_session['hits']} hit / {semantic_session['misses']} miss / {semantic_session['bypassed']} bypass",
            f"    Eligible hit rate: {semantic_session['hit_rate']:.1f}% (eligible: {semantic_session['eligibility_rate']:.1f}%, bypass: {semantic_session['bypass_rate']:.1f}%)",
            "",
            "  Commands: /cache clear | /cache clean",
        ]
        return {
            "action": "cache_stats",
            "message": "\n".join(lines),
            "application_cache": app_stats,
            "provider_cache": {
                "prompt_tokens": token_stats.prompt_tokens,
                "hit_tokens": token_stats.cache_hit_tokens,
                "hit_rate": round(token_stats.cache_hit_rate, 2),
            },
        }


    # ── /queue ──────────────────────────────────────────────
    if c == "/queue":
        queue_manager = _state.get("queue_manager")
        if queue_manager is None:
            return {"action": "error", "message": "Task queue service is not running"}
        if not args:
            tasks = queue_manager.list_tasks()
            return {
                "action": "queue_list",
                "message": "任务队列为空" if not tasks else "\n".join(
                    f"  [{task['id']}] ({task['status']}) {task['prompt']}"
                    for task in tasks
                ),
                "tasks": tasks,
            }
        sub_parts = args.split(None, 1)
        sub = sub_parts[0].lower()
        sub_args = sub_parts[1] if len(sub_parts) > 1 else ""
        if sub == "add" and sub_args:
            task = queue_manager.add_task(sub_args)
            return {
                "action": "queue_add",
                "message": f"已添加任务 #{task['id']}: {sub_args}",
                "task": task,
            }
        elif sub == "list":
            tasks = queue_manager.list_tasks()
            return {
                "action": "queue_list",
                "message": "任务队列为空" if not tasks else "\n".join(
                    f"  [{task['id']}] ({task['status']}) {task['prompt']}"
                    for task in tasks
                ),
                "tasks": tasks,
            }
        elif sub == "clear":
            queue_manager.clear()
            return {"action": "queue_clear", "message": "已清空任务队列"}
        elif sub == "remove":
            try:
                task_id = int(sub_args)
            except ValueError:
                return {"action": "error", "message": "任务 ID 必须是数字"}
            if not queue_manager.remove(task_id):
                return {"action": "error", "message": f"任务未找到: {task_id}"}
            return {"action": "queue_remove", "message": f"已移除任务: {task_id}"}
        elif sub == "run":
            async def runner(prompt):
                return await _run_service_prompt(
                    prompt, "queue", acquire_lock=False
                )
            if not sub_args or sub_args.lower() == "all":
                tasks = await queue_manager.run_all_async(runner)
                return {
                    "action": "queue_run",
                    "message": f"已执行 {len(tasks)} 个任务",
                    "tasks": tasks,
                }
            try:
                task_id = int(sub_args)
            except ValueError:
                return {"action": "error", "message": "任务 ID 必须是数字"}
            task = await queue_manager.run_task_async(task_id, runner)
            if task is None:
                return {
                    "action": "error",
                    "message": f"任务未找到或不是 pending 状态: {task_id}",
                }
            return {
                "action": "queue_run",
                "message": f"任务 #{task_id} 已结束: {task['status']}",
                "task": task,
            }
        else:
            return {"action": "queue", "message": "用法: /queue add|list|clear|remove|run [id|all]"}

    # ── /schedule ───────────────────────────────────────────
    if c == "/schedule":
        scheduler = _state.get("scheduler")
        if scheduler is None:
            return {"action": "error", "message": "Scheduler service is disabled or not running"}

        def task_payload(task):
            return task.to_dict()

        if not args:
            tasks = scheduler.list_tasks()
            if not tasks:
                return {
                    "action": "schedule_list",
                    "message": "没有定时任务",
                    "tasks": [],
                }
            lines = ["定时任务:"]
            for t in tasks:
                status = "enabled" if t.enabled else "disabled"
                runs = f"runs={t.run_count}" if t.run_count else ""
                last = f"last={t.last_run[:19]}" if t.last_run else ""
                meta = " ".join(x for x in [runs, last] if x)
                lines.append(f"  {t.id}  {t.cron_expr:<16}  [{status}]  {meta}")
                lines.append(f"    {t.prompt}")
            return {
                "action": "schedule_list",
                "message": "\n".join(lines),
                "tasks": [task_payload(task) for task in tasks],
            }
        sub_parts = args.split(None, 1)
        sub = sub_parts[0].lower()
        sub_args = sub_parts[1] if len(sub_parts) > 1 else ""
        if sub == "add" and sub_args:
            add_parts = sub_args.split()
            if add_parts and add_parts[0] == "@every" and len(add_parts) >= 3:
                cron_expr = " ".join(add_parts[:2])
                prompt = " ".join(add_parts[2:])
            elif add_parts and add_parts[0].startswith("@"):
                cron_expr = add_parts[0]
                prompt = " ".join(add_parts[1:])
            elif len(add_parts) >= 6:
                cron_expr = " ".join(add_parts[:5])
                prompt = " ".join(add_parts[5:])
            else:
                return {
                    "action": "error",
                    "message": "用法: /schedule add <cron> <prompt>",
                }
            if not prompt:
                return {"action": "error", "message": "缺少任务描述"}
            try:
                task = scheduler.add_task(cron_expr, prompt)
                return {
                    "action": "schedule_add",
                    "message": f"已添加定时任务 {task.id}: {cron_expr} -> {prompt}",
                    "task": task_payload(task),
                }
            except ValueError as e:
                return {"action": "error", "message": f"无效的 cron 表达式: {e}"}
        elif sub == "remove" and sub_args:
            if scheduler.remove_task(sub_args):
                return {"action": "schedule_remove", "message": f"已移除任务 {sub_args}"}
            return {"action": "error", "message": f"任务未找到: {sub_args}"}
        elif sub == "enable" and sub_args:
            if scheduler.enable_task(sub_args):
                return {"action": "schedule_enable", "message": f"已启用任务 {sub_args}"}
            return {"action": "error", "message": f"任务未找到: {sub_args}"}
        elif sub == "disable" and sub_args:
            if scheduler.disable_task(sub_args):
                return {"action": "schedule_disable", "message": f"已禁用任务 {sub_args}"}
            return {"action": "error", "message": f"任务未找到: {sub_args}"}
        elif sub == "run" and sub_args:
            ran = await scheduler.run_task_async(
                sub_args,
                lambda prompt: _run_service_prompt(
                    prompt, "scheduled", acquire_lock=False
                ),
            )
            if not ran:
                return {"action": "error", "message": f"任务未找到: {sub_args}"}
            task = scheduler.get_task(sub_args)
            return {
                "action": "schedule_run",
                "message": f"定时任务 {sub_args} 已结束: {task.last_status}",
                "task": task_payload(task),
            }
        elif sub == "list":
            tasks = scheduler.list_tasks()
            lines = ["定时任务:"] + [f"  {t.id} [{('enabled' if t.enabled else 'disabled')}] {t.cron_expr} -> {t.prompt[:60]}" for t in tasks]
            return {
                "action": "schedule_list",
                "message": "\n".join(lines) if tasks else "没有定时任务",
                "tasks": [task_payload(task) for task in tasks],
            }
        else:
            return {"action": "schedule", "message": "用法: /schedule add|list|remove|enable|disable|run"}

    # ── /save-chat ──────────────────────────────────────────
    if c == "/save-chat" or c.startswith("/save-chat"):
        from .memory.chat_storage import chat_storage
        name = args if args else (c[len("/save-chat-"):] if c.startswith("/save-chat-") and c != "/save-chat" else "")
        if not name:
            if _state["chat_history"]:
                name = _state["chat_history"][0].get("content", "")[:50]
            else:
                name = f"chat_{len(chat_storage.list_chats())}"
        if chat_storage.save(name, _state["chat_history"]):
            return {
                "action": "chat_saved",
                "message": f"对话已保存: {name}",
                "schema_version": CHAT_SCHEMA_VERSION,
            }
        return {"action": "error", "message": "保存对话失败"}

    # ── /load-chat ──────────────────────────────────────────
    if c == "/load-chat" or c.startswith("/load-chat"):
        from .memory.chat_storage import chat_storage
        name = args if args else (c[len("/load-chat-"):] if c.startswith("/load-chat-") and c != "/load-chat" else "")
        if not name:
            chats = chat_storage.list_chats()
            if not chats:
                return {"action": "chat_list", "message": "没有已保存的对话", "chats": []}
            chat_names = [f"  {ch.get('name', '')}" for ch in chats[:10]]
            return {"action": "chat_list", "message": "已保存的对话:\n" + "\n".join(chat_names), "chats": chats}
        record = chat_storage.load_record(name)
        if record is not None:
            messages = record["messages"]
            history[:] = messages
            _state["chat_history"] = history
            _state.setdefault("chat_histories", {})[req.session_id] = history
            agent = _state.get("agent")
            if agent is not None:
                agent._memory.clear()
                agent._memory.short_term.load_from_dicts(messages)
                agent._session_loaded = True
            return {
                "action": "chat_loaded",
                "message": f"对话已加载: {name}",
                "messages": messages,
                "schema_version": record["schema_version"],
            }
        return {"action": "error", "message": f"对话未找到: {name}"}

    # ── /tutorial ───────────────────────────────────────────
    if c == "/tutorial":
        return {"action": "tutorial", "message": "🎓 RxyCode 交互式教程\n\n1. 基本对话: 直接输入问题或需求\n2. 文件操作: '读取/编辑/创建文件'\n3. 代码开发: '写一个函数/类/模块'\n4. 项目管理: '运行测试/提交代码'\n5. 模式切换: /plan /build /compose\n6. 记忆管理: /memory add/list/search\n7. 任务调度: /schedule add/list\n\n试试: '创建一个 Python 计算器' 或 '分析当前项目结构'"}

    # ── /quickstart ─────────────────────────────────────────
    if c == "/quickstart":
        return {"action": "quickstart", "message": "🚀 RxyCode 快速入门\n\n• 输入自然语言描述需求\n• RxyCode 会自动理解并执行\n• 支持代码开发、文件操作、项目管理\n\n常用命令:\n  /help      帮助\n  /clear     清除上下文\n  /models    列出模型\n  /memory    管理记忆\n  /queue     任务队列\n\n开始吧！试试输入你的第一个需求。"}

    # ── /examples ───────────────────────────────────────────
    if c == "/examples":
        return {"action": "examples", "message": "📚 RxyCode 使用示例\n\n代码开发:\n  • '写一个 Python 函数实现快速排序'\n  • '创建一个 React 组件显示用户列表'\n  • '重构这个函数，提高可读性'\n\n文件操作:\n  • '读取 README.md 文件'\n  • '搜索所有包含 TODO 的 Python 文件'\n  • '编辑 main.py 中的配置部分'\n\n项目管理:\n  • '查看当前 Git 状态'\n  • '运行所有单元测试'\n  • '提交代码到本地仓库'\n\n问题排查:\n  • '分析这个错误信息'\n  • '为什么这段代码运行缓慢'\n\n技术调研:\n  • '搜索 Python 异步编程最佳实践'\n  • '研究 React Hooks 的使用方法'"}

    # ── /resave-chatname ────────────────────────────────────
    if c == "/resave-chatname" or c.startswith("/resave-chatname"):
        from .memory.chat_storage import chat_storage
        new_name = args if args else (c[len("/resave-chatname-"):] if c.startswith("/resave-chatname-") and c != "/resave-chatname" else "")
        if not new_name:
            return {"action": "error", "message": "用法: /resave-chatname <new_name>"}
        old_chats = chat_storage.list_chats()
        if old_chats:
            old_name = old_chats[0].get("name", "")
            if chat_storage.rename(old_name, new_name):
                return {"action": "chat_renamed", "message": f"对话已重命名: {old_name} -> {new_name}"}
        return {"action": "error", "message": "重命名失败"}

    # ── /find-skill ──────────────────────────────────────────
    if c == "/find-skill":
        if not args:
            return {"action": "error", "message": "Usage: /find-skill <skill-name>\nExample: /find-skill coding-workflow"}
        result, ok = await _execute_explicit_command_tool(
            "download_skill", {"name": args, "operation": "install"}
        )
        return {"action": "skill_installed" if ok else "error", "message": result}

    # ── /addskill ────────────────────────────────────────────
    if c == "/addskill":
        if not args:
            return {"action": "error", "message": "Usage: /addskill <name-or-url>"}
        if args.startswith("http://") or args.startswith("https://"):
            parts = args.split()
            url = parts[0]
            if len(parts) > 1:
                name = parts[1]
            else:
                from urllib.parse import urlparse
                name = Path(Path(urlparse(url).path).name).stem or "downloaded-skill"
            tool_args = {"name": name, "operation": "install_url", "url": url}
        else:
            tool_args = {"name": args, "operation": "install"}
        result, ok = await _execute_explicit_command_tool("download_skill", tool_args)
        return {"action": "skill_installed" if ok else "error", "message": result}

    # ── /list-skills ─────────────────────────────────────────
    if c == "/list-skills":
        from .tools.skill_manager import list_installed_skills
        skills = list_installed_skills()
        if not skills:
            return {"message": "No skills installed. Use /find-skill <name> to install.", "skills": []}
        lines = [f"  {s['name']} {'(OK)' if s.get('has_skill_md') else '(no SKILL.md)'}" for s in skills]
        return {"message": "\n".join(lines), "skills": skills}

    # ── /remove-skill ────────────────────────────────────────
    if c == "/remove-skill":
        if not args:
            return {"action": "error", "message": "Usage: /remove-skill <name>"}
        result, ok = await _execute_explicit_command_tool(
            "download_skill", {"name": args, "operation": "remove"}
        )
        return {"action": "skill_removed" if ok else "error", "message": result}

    # ── /addmcp ──────────────────────────────────────────────
    if c == "/addmcp":
        if not args:
            return {"action": "error", "message": "Usage: /addmcp <name> <command> [args...]\nExample: /addmcp my-server npx -y @modelcontextprotocol/server-filesystem"}
        parts = args.split()
        if len(parts) < 2:
            return {"action": "error", "message": "Usage: /addmcp <name> <command> [args...]"}
        name = parts[0]
        mcp_command = parts[1]
        mcp_args = parts[2:] if len(parts) > 2 else []
        result, ok = await _execute_explicit_command_tool(
            "download_mcp",
            {
                "name": name,
                "operation": "add",
                "command": mcp_command,
                "args": mcp_args,
            },
        )
        return {"action": "mcp_added" if ok else "error", "message": result}

    # ── /list-mcp ────────────────────────────────────────────
    if c == "/list-mcp":
        from .tools.mcp_manager import list_mcp_servers
        servers = list_mcp_servers()
        if not servers:
            return {"message": "No MCP servers configured. Use /addmcp to add one.", "servers": []}
        lines = [f"  {s['name']}: {s['command']} {' '.join(s.get('args', []))}" for s in servers]
        return {"message": "\n".join(lines), "servers": servers}

    # ── /remove-mcp ─────────────────────────────────────────
    if c == "/remove-mcp":
        if not args:
            return {"action": "error", "message": "Usage: /remove-mcp <name>"}
        result, ok = await _execute_explicit_command_tool(
            "download_mcp", {"name": args, "operation": "remove"}
        )
        return {"action": "mcp_removed" if ok else "error", "message": result}

    # 模糊匹配命令
    known_commands = [
        "/help", "/clear", "/models", "/model", "/addmodel",
        "/plan", "/build", "/compose", "/language", "/memory",
        "/list-chats", "/save-chat", "/load-chat", "/queue",
        "/schedule", "/cache", "/thinking", "/mode", "/exit",
        "/tutorial", "/quickstart", "/examples",
        "/find-skill", "/addskill", "/list-skills", "/remove-skill",
        "/addmcp", "/list-mcp", "/remove-mcp",
    ]
    # 前缀匹配
    suggestions = [k for k in known_commands if k.startswith(cmd.lower())]
    # 如果前缀匹配失败，尝试编辑距离匹配（允许2个字符错误）
    if not suggestions and len(cmd) > 2:
        for k in known_commands:
            k_lower = k.lower()
            # 简单的字符交换/替换检测
            if len(cmd) == len(k_lower):
                diff = sum(1 for a, b in zip(cmd.lower(), k_lower) if a != b)
                if diff <= 2:
                    suggestions.append(k)
    if suggestions:
        return {"action": "unknown", "message": f"Unknown command: {cmd}\nDid you mean: {', '.join(suggestions)}?"}
    return {"action": "unknown", "message": f"Unknown command: {cmd}"}


@app.post("/cancel")
async def cancel_active_run():
    """Cancel whichever chat or slash command currently owns the agent."""
    cancelled = _api_run_lifecycle.cancel()
    try:
        from .core.question import get_question_broker

        question_broker = get_question_broker()
        if question_broker is not None:
            cancelled = bool(question_broker.cancel_all()) or cancelled
    except Exception:
        pass
    agent = _state.get("agent")
    if not cancelled and agent is not None:
        cancel = getattr(agent, "cancel", None)
        if callable(cancel):
            cancelled = bool(cancel())
    return {
        "action": "cancelling" if cancelled else "idle",
        "cancelled": cancelled,
        "active_kind": _api_run_lifecycle.active_kind,
    }


@app.post("/command")
async def command(req: CommandRequest):
    """Execute every slash command in the same serial lifecycle as chat."""
    command_parts = req.command.strip().split(None, 1)
    if command_parts and command_parts[0].lower() == "/cancel":
        return await cancel_active_run()

    async def run_command():
        async with _chat_lock:
            run_id = _uuid.uuid4().hex
            from .core.tracing import Tracer
            from .log.logger import run_id_context
            from .log.monitor import run_monitor

            agent = _state.get("agent")
            previous_tracer = getattr(agent, "_tool_tracer", None) if agent else None
            started_at = _time.monotonic()
            terminal_status = "failed"
            with run_id_context(run_id):
                try:
                    if agent is not None:
                        agent._tool_tracer = Tracer(run_id=run_id)
                    result = await _execute_command(req)
                    if result.get("action") == "error":
                        classified, _detail = classify_agent_result(
                            str(result.get("message", ""))
                        )
                        terminal_status = (
                            classified if classified != "succeeded" else "failed"
                        )
                    else:
                        terminal_status = "succeeded"
                    return result
                except _asyncio.CancelledError:
                    terminal_status = "cancelled"
                    raise
                finally:
                    if agent is not None:
                        agent._tool_tracer = previous_tracer
                    run_monitor.record(
                        run_id, terminal_status, _time.monotonic() - started_at
                    )

    try:
        return await _api_run_lifecycle.run(run_command, kind="command")
    except _asyncio.CancelledError:
        return {"action": "cancelled", "message": "Command cancelled"}


class StreamSessionRecorder:
    """Mirror one real SSE turn into the durable session message protocol."""

    def __init__(self, history: list[dict], *, run_id: str, user_message: str) -> None:
        self._history = history
        self.run_id = run_id
        self.started_at = _time.monotonic()
        self._thinking_parts: list[str] = []
        self._has_thinking_content = False
        self._pending_tools: list[dict] = []
        self._terminal = False
        self._append("user", user_message)
        self._thinking = self._append(
            "thinking", "Analyzing request...", done=False, live=True
        )

    @property
    def messages(self) -> list[dict]:
        return [message for message in self._history if message.get("run_id") == self.run_id]

    @property
    def thinking_content(self) -> str:
        if not self._has_thinking_content:
            return ""
        return str(self._thinking.get("content", "") or "")

    def _append(self, role: str, content: str, **metadata) -> dict:
        message = _session_message(role, content, run_id=self.run_id, **metadata)
        self._history.append(message)
        return message

    def add_thinking(self, text: str) -> None:
        if text:
            self._has_thinking_content = True
            self._thinking_parts.append(str(text))
            self._thinking["content"] = "".join(self._thinking_parts)

    def set_plan(self, steps: list) -> None:
        self._has_thinking_content = True
        content = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, 1))
        self._thinking["content"] = f"Plan ({len(steps)} steps):\n{content}"

    def set_step(self, index: int, total: int, text: str) -> None:
        self.add_thinking(f"Step {index}/{total}: {text}")
        self._thinking["stepIndex"] = index
        self._thinking["stepTotal"] = total

    def start_tool(self, name: str, args, call_id: str | None = None) -> dict:
        message = self._append(
            "tool",
            "",
            id=call_id or f"{self.run_id}-tool-{_uuid.uuid4().hex[:10]}",
            toolName=str(name),
            toolArgs=str(args),
            toolStatus="running",
            toolStdout="",
            _started_at=_time.monotonic(),
        )
        self._pending_tools.append(message)
        return message

    def finish_tool(
        self, result, status: str, call_id: str | None = None
    ) -> dict | None:
        running = [
            candidate
            for candidate in self._pending_tools
            if candidate.get("toolStatus") == "running"
        ]
        message = next(
            (candidate for candidate in running if candidate.get("id") == call_id),
            running[0] if call_id is None and len(running) == 1 else None,
        )
        if message is None:
            return None
        output = str(result)
        normalized_status = {
            "failed": "error",
            "timed_out": "timeout",
        }.get(str(status), str(status))
        started_at = float(message.pop("_started_at", _time.monotonic()))
        message.update({
            "content": output,
            "toolStdout": output,
            "toolStatus": normalized_status,
            "toolDuration": max(0.0, _time.monotonic() - started_at),
        })
        exit_match = re.search(r"\[?\s*exit(?:\s*code)?\s*:\s*(-?\d+)\s*\]?", output, re.I)
        if exit_match:
            message["toolExitCode"] = int(exit_match.group(1))
        if normalized_status in {"error", "timeout", "cancelled"}:
            message["toolError"] = output
        return message

    def add_system_error(self, detail: str) -> dict:
        return self._append("system", f"Error: {detail}")

    def finish_success(self, answer: str, thinking: str) -> None:
        if self._terminal:
            return
        self._terminal = True
        if thinking:
            self._thinking["content"] = thinking
        elif not self._thinking_parts:
            self._thinking["content"] = "Done"
        self._finish_pending_tools("error")
        self._finish_thinking()
        self._append(
            "assistant",
            answer,
            elapsed=max(0.0, _time.monotonic() - self.started_at),
        )

    def finish_error(self, detail: str) -> None:
        if self._terminal:
            return
        self._terminal = True
        self._finish_pending_tools("error")
        self._finish_thinking()
        self.add_system_error(detail)

    def finish_cancelled(self) -> None:
        if self._terminal:
            return
        self._terminal = True
        self._thinking["content"] = self._thinking.get("content") or "Cancelled"
        self._finish_pending_tools("cancelled")
        self._finish_thinking()
        self._append("system", "Cancelled")

    def _finish_pending_tools(self, status: str) -> None:
        for message in self._pending_tools:
            if message.get("toolStatus") != "running":
                continue
            started_at = float(message.pop("_started_at", _time.monotonic()))
            message["toolStatus"] = status
            message["toolDuration"] = max(0.0, _time.monotonic() - started_at)

    def _finish_thinking(self) -> None:
        self._thinking.update({
            "done": True,
            "live": False,
            "elapsed": max(0.0, _time.monotonic() - self.started_at),
        })


class StreamTUI:
    """TUI implementation that pushes structured events onto a queue so the
    agent's progress can be streamed to the client as Server-Sent Events.

    This is what powers the mainstream-style "think -> tell the user what I'm
    doing -> keep working -> stream the final answer" experience."""

    # Stream coalescing paradigm ported from google-gemini/gemini-cli
    # (Apache-2.0, https://github.com/google-gemini/gemini-cli):
    # high-frequency stream chunks are accumulated per type and flushed on a
    # fixed time tick instead of emitting one SSE event per chunk, so the
    # frontend renders in a single tick and never floods/flickers.
    FLUSH_INTERVAL_S = 0.07
    TOOL_RESULT_MAX_CHARS = 4096
    TOOL_RESULT_MAX_LINES = 60

    def __init__(
        self,
        queue: "_asyncio.Queue",
        recorder: StreamSessionRecorder | None = None,
    ):
        self.q = queue
        self.recorder = recorder
        self._expand_thinking = False
        # per-type accumulation buffers (dict order defines flush order)
        self._buffers: dict[str, list[str]] = {"reasoning": [], "progress": [], "token": []}
        self._last_flush = 0.0  # monotonic; 0 -> first chunk flushes at once

    def _put(self, ev: dict):
        try:
            self.q.put_nowait(ev)
        except Exception:
            pass

    # -- coalescing core (B1) -------------------------------------------
    def flush_stream_buffers(self):
        """Emit all buffered chunk types as single merged events."""
        for kind, buf in self._buffers.items():
            if buf:
                text = "".join(buf)
                buf.clear()
                self._put({"type": kind, "text": text})
        self._last_flush = _time.monotonic()

    def _buffer(self, kind: str, text: str):
        self._buffers[kind].append(text)
        if _time.monotonic() - self._last_flush >= self.FLUSH_INTERVAL_S:
            self.flush_stream_buffers()

    # Internal-monologue patterns that must never reach the client while
    # thinking is off (B2/B5): raw reasoning rounds, code dumps, char counters.
    _NOISY_PROGRESS = re.compile(
        r"^(Thinking\.\.\.|Analyzing|Synthesizing|\[Code block:|Generating\.\.\.)"
    )

    # progress / plan / steps / tools / streamed tokens
    def write_progress(self, text):
        text = str(text)
        if self.recorder: self.recorder.add_thinking(text)
        # Gating (B2, 问题5/6): with thinking off, only short single-line
        # status updates pass (frontend loading phrase); internal monologue,
        # multi-line or long content is suppressed from SSE.
        if not self._expand_thinking:
            if "\n" in text or len(text) >= 150 or self._NOISY_PROGRESS.match(text):
                return
        self._buffer("progress", text + "\n")
    def write_reasoning(self, text):
        if self.recorder: self.recorder.add_thinking(str(text))
        if self._expand_thinking:
            self._buffer("reasoning", str(text))
    def write(self, text, color=""): self.write_progress(text)
    def write_info(self, text): self.write_progress(text)
    def write_success(self, text): self.write_progress(text)
    def write_warning(self, text): self.write_progress(text)
    def write_error(self, text):
        self.flush_stream_buffers()
        message = self.recorder.add_system_error(str(text)) if self.recorder else None
        self._put({"type": "error", "message": str(text), "message_id": message.get("id") if message else None})
    def write_plan(self, steps):
        self.flush_stream_buffers()
        values = list(steps)
        if self.recorder: self.recorder.set_plan(values)
        self._put({"type": "plan", "steps": values})
    def write_step(self, num, total, desc):
        self.flush_stream_buffers()
        if self.recorder: self.recorder.set_step(num, total, str(desc))
        self._put({"type": "step", "index": num, "total": total, "text": str(desc)})
    def write_tool_call(self, name, args, call_id=None):
        self.flush_stream_buffers()
        message = (
            self.recorder.start_tool(name, args, call_id=call_id)
            if self.recorder
            else None
        )
        call_id = message["id"] if message else str(call_id or _uuid.uuid4().hex)
        self._put({
            "type": "tool_call", "name": name, "args": str(args),
            "message_id": call_id,
            "timestamp": message.get("timestamp") if message else None,
        })
        return call_id
    def _truncate_for_sse(self, text: str) -> tuple[str, bool]:
        """Cap tool output on the SSE channel (B3); full output stays in recorder."""
        truncated = False
        lines = text.splitlines()
        if len(lines) > self.TOOL_RESULT_MAX_LINES:
            text = "\n".join(lines[: self.TOOL_RESULT_MAX_LINES])
            truncated = True
        if len(text) > self.TOOL_RESULT_MAX_CHARS:
            text = text[: self.TOOL_RESULT_MAX_CHARS]
            truncated = True
        if truncated:
            text += "\n… [输出已截断，完整结果见会话历史]"
        return text, truncated
    def write_tool_result(self, result, status="success", call_id=None):
        self.flush_stream_buffers()
        message = (
            self.recorder.finish_tool(result, status, call_id=call_id)
            if self.recorder
            else None
        )
        normalized_status = message.get("toolStatus") if message else status
        sse_result, was_truncated = self._truncate_for_sse(str(result))
        event = {"type": "tool_result", "result": sse_result, "status": normalized_status}
        if was_truncated:
            event["truncated"] = True
        if message:
            event.update({
                "message_id": message["id"],
                "duration": message.get("toolDuration"),
                "error": message.get("toolError"),
                "exitCode": message.get("toolExitCode"),
            })
        elif call_id is not None:
            event["message_id"] = str(call_id)
        self._put(event)
    def stream_token(self, tok):
        # Answer tokens always pass (thinking gating never hides the answer).
        self._buffer("token", str(tok))

    # no-ops for the rest of the TUI interface
    def set_thinking_expanded(self, expanded):
        was = bool(getattr(self, "_expand_thinking", False))
        self._expand_thinking = bool(expanded)
        # Mid-run expand: push already-accumulated thinking so the client can
        # show it immediately (U3). Collapse must not replay.
        if self._expand_thinking and not was:
            self._emit_thinking_snapshot()

    def _emit_thinking_snapshot(self) -> None:
        self.flush_stream_buffers()
        snapshot = ""
        if self.recorder is not None:
            snapshot = str(self.recorder.thinking_content or "")
        if not snapshot:
            return
        self._put({"type": "reasoning", "text": snapshot, "snapshot": True})

    def get_thinking_expanded(self):
        """Get thinking panel expanded state (always False in stream mode unless set)."""
        return getattr(self, '_expand_thinking', False)
    def set_mode(self, *a): pass
    def set_model(self, *a): pass
    def set_busy(self, *a): pass
    def write_user_input(self, *a): pass
    def write_model_indicator(self, *a): pass
    def write_capability_list(self, *a): pass
    def write_command_list(self, *a): pass
    def write_chat_list(self, *a): pass
    def update_stats(self, *a, **k): pass
    def __getattr__(self, name):
        def _f(*a, **k): return None
        return _f


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Stream the agent's progress + answer as Server-Sent Events."""
    if not _state["agent"]:
        try:
            _init_agent()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Agent not initialized: {e}")

    # Validate empty message
    if not req.message or not req.message.strip():
        return StreamingResponse(iter(['data: {"type":"error","content":"Empty message"}\n\n', 'data: {"type":"done"}\n\n']),
                                 media_type="text/event-stream; charset=utf-8")

    # Validate mode
    valid_modes = ("build", "plan", "compose")
    if req.mode not in valid_modes:
        async def error_gen():
            yield f"data: {_json.dumps({'type': 'error', 'message': f'Invalid mode: {req.mode}'})}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    # Bug A (defense-in-depth): refuse a new turn while one is already
    # streaming.  The frontend already blocks duplicate sends, but this
    # guarantees the backend never runs N parallel agent calls (which
    # previously meant three "你好" each burning 26-38s and looking like a hang).
    if _state.get("busy"):
        async def busy_gen():
            yield f"data: {_json.dumps({'type': 'error', 'message': 'Agent is busy: please wait for the current response to finish before sending another message.'})}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
        return StreamingResponse(busy_gen(), media_type="text/event-stream")

    queue: "_asyncio.Queue" = _asyncio.Queue()
    stream_tui = StreamTUI(queue)
    # Inherit thinking expanded state from the global proxy
    if _state.get("tui_proxy"):
        stream_tui._expand_thinking = getattr(_state["tui_proxy"], "_expand_thinking", False)

    agent = _state["agent"]
    run_id = _uuid.uuid4().hex

    async def runner():
        status = "failed"
        started_at = _time.monotonic()
        from .core.tracing import Tracer
        from .log.monitor import run_monitor
        tracer = Tracer(run_id=run_id)
        root_span = tracer.start_span("agent_run")
        recorder: StreamSessionRecorder | None = None

        async def run_serialized():
            nonlocal status, recorder
            async with _chat_lock:
                from .core.safety.approval import get_approval_broker, SseApproval
                from .core.question import get_question_broker, SseQuestionBroker
                from .utils.tui import set_tui, get_tui

                broker = get_approval_broker()
                previous_sink = broker._sink if isinstance(broker, SseApproval) else None
                question_broker = get_question_broker()
                previous_question_sink = (
                    question_broker._sink
                    if isinstance(question_broker, SseQuestionBroker)
                    else None
                )
                stream_loop = _asyncio.get_running_loop()
                stream_question_ids: set[str] = set()

                def publish_question(event: dict) -> None:
                    question_id = str(event.get("question_id", ""))
                    if question_id:
                        stream_question_ids.add(question_id)
                    try:
                        current_loop = _asyncio.get_running_loop()
                    except RuntimeError:
                        current_loop = None
                    if current_loop is stream_loop:
                        queue.put_nowait(event)
                    elif stream_loop.is_running():
                        stream_loop.call_soon_threadsafe(queue.put_nowait, event)

                previous_tui = get_tui()
                previous_tracer = getattr(agent, "_tool_tracer", None)
                history = _activate_session(agent, req.session_id)
                recorder = StreamSessionRecorder(
                    history, run_id=run_id, user_message=req.message
                )
                stream_tui.recorder = recorder
                _state["mode"] = req.mode
                set_tui(stream_tui)
                if isinstance(broker, SseApproval):
                    broker.set_event_sink(queue.put_nowait)
                if isinstance(question_broker, SseQuestionBroker):
                    question_broker.set_event_sink(publish_question)
                try:
                    agent._stream_mode = True
                    agent._tool_tracer = tracer
                    log_chat_request(_logger, req.mode, req.message, run_id=run_id)
                    from .utils.streaming import token_stats as _ts
                    previous_input = _ts.input_tokens
                    previous_output = _ts.output_tokens
                    thinking_cursor = _thinking_cursor(agent)
                    answer = await agent.run(req.message, mode=req.mode)
                    status, detail = classify_agent_result(answer)
                    delta_input = _ts.input_tokens - previous_input
                    delta_output = _ts.output_tokens - previous_output
                    thinking = (
                        recorder.thinking_content
                        or _thinking_since(agent, thinking_cursor)
                    )
                    stream_tui.flush_stream_buffers()
                    if status == "succeeded":
                        recorder.finish_success(answer, thinking)
                        log_chat_completed(_logger, req.mode, answer, run_id=run_id, status=status)
                        queue.put_nowait({
                            "type": "final",
                            "run_id": run_id,
                            "text": answer,
                            "thinking": thinking,
                            "input_tokens": delta_input,
                            "output_tokens": delta_output,
                            "session_schema_version": CHAT_SCHEMA_VERSION,
                        })
                    else:
                        recorder.finish_error(detail)
                        log_chat_error(_logger, req.mode, detail, run_id=run_id, status=status)
                        queue.put_nowait({"type": "error", "run_id": run_id, "status": status, "message": detail})
                except _asyncio.CancelledError:
                    status = "cancelled"
                    recorder.finish_cancelled()
                    log_chat_error(_logger, req.mode, "stream cancelled", run_id=run_id, status=status)
                    raise
                except Exception as exc:
                    status = "failed"
                    stream_tui.flush_stream_buffers()
                    recorder.finish_error(str(exc))
                    log_chat_error(_logger, req.mode, exc, run_id=run_id, status=status)
                    queue.put_nowait({"type": "error", "run_id": run_id, "status": status, "message": str(exc)})
                finally:
                    agent._tool_tracer = previous_tracer
                    agent._stream_mode = False
                    set_tui(previous_tui)
                    if isinstance(broker, SseApproval):
                        broker.set_event_sink(previous_sink)
                    if isinstance(question_broker, SseQuestionBroker):
                        for question_id in stream_question_ids:
                            question_broker.cancel(question_id)
                        question_broker.set_event_sink(previous_question_sink)

        try:
            await _api_run_lifecycle.run(run_serialized, kind="chat_stream")
        except _asyncio.CancelledError:
            status = "cancelled"
        except Exception as exc:
            # 生命周期包装层（超时/调度/其他内部异常）在 run_serialized 之外抛错。
            # run_serialized 自身异常已由内层 except 捕获并发 error 事件，这里只兜底
            # 外层逃逸异常：先把已缓冲内容 flush 出去，再向前端发 error 事件，
            # 最后由 finally 发 done，避免流静默关闭（0 error 事件、前端无可见失败原因）。
            status = "failed"
            stream_tui.flush_stream_buffers()
            log_chat_error(_logger, req.mode, exc, run_id=run_id, status=status)
            queue.put_nowait({"type": "error", "run_id": run_id, "status": status, "message": str(exc)})
        finally:
            duration_s = _time.monotonic() - started_at
            trace_status = {
                "succeeded": "ok",
                "timed_out": "timeout",
                "cancelled": "cancelled",
            }.get(status, "error")
            tracer.end_span(root_span, status=trace_status)
            run_monitor.record(run_id, status, duration_s)
            _state["busy"] = False
            stream_tui.flush_stream_buffers()
            queue.put_nowait({"type": "done", "run_id": run_id, "status": status})

    _state["busy"] = True
    from .log.logger import run_id_context
    with run_id_context(run_id):
        task = _asyncio.create_task(runner())

    async def event_gen():
        try:
            while True:
                ev = await queue.get()
                yield f"data: {_json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("type") == "done":
                    break
        finally:
            if not task.done():
                task.cancel()
            # A cancelled/disconnected stream must not return until runner()
            # has released _chat_lock and restored its process-wide state.
            with suppress(_asyncio.CancelledError):
                await task

    return StreamingResponse(event_gen(), media_type="text/event-stream; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def run_api_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    token: str | None = None,
    ssl_certfile: str | os.PathLike[str] | None = None,
    ssl_keyfile: str | os.PathLike[str] | None = None,
    ssl_keyfile_password: str | None = None,
):
    """Start the API server; every non-loopback socket requires TLS."""
    _ensure_utf8_stdio()
    remote_bind = not _is_loopback_bind_host(host)
    if remote_bind and not _remote_api_opted_in():
        raise RuntimeError(
            "Refusing non-loopback API bind without RXYCODE_ALLOW_REMOTE_API=1"
        )
    if remote_bind:
        configured_token = token or os.environ.get("RXYCODE_API_TOKEN")
        configured_token = _validate_remote_token(configured_token)
        ssl_certfile = ssl_certfile or os.environ.get("RXYCODE_TLS_CERTFILE")
        ssl_keyfile = ssl_keyfile or os.environ.get("RXYCODE_TLS_KEYFILE")
        if not ssl_certfile or not ssl_keyfile:
            raise RuntimeError(
                "Remote API access requires RXYCODE_TLS_CERTFILE and "
                "RXYCODE_TLS_KEYFILE"
            )
        cert_path = Path(ssl_certfile).expanduser().resolve()
        key_path = Path(ssl_keyfile).expanduser().resolve()
        if not cert_path.is_file() or not key_path.is_file():
            raise RuntimeError("Remote API TLS certificate or key file does not exist")
        configure_api_access(allow_remote=True, token=configured_token)
    else:
        configure_api_access(allow_remote=False, token=token)
    import uvicorn
    options = {"host": host, "port": port, "log_level": "warning"}
    if remote_bind:
        options.update({
            "ssl_certfile": str(cert_path),
            "ssl_keyfile": str(key_path),
            "ssl_keyfile_password": (
                ssl_keyfile_password
                or os.environ.get("RXYCODE_TLS_KEYFILE_PASSWORD")
            ),
        })
        if options["ssl_keyfile_password"] is None:
            options.pop("ssl_keyfile_password")
    uvicorn.run(app, **options)


if __name__ == "__main__":
    run_api_server()




