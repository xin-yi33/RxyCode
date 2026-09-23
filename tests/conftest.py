"""Shared isolation and deterministic fixtures for the RxyCode test suite."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from string import Template
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# Checkout-local package binding (runs before ANY project import).
#
# The editable install maps ``RxyCode.RxyCode1_1_0`` to the main working tree
# (``D:\\agent-demo\\RxyCode\\RxyCode1_1_0``), which can diverge from the
# checkout under test (worktree/branch).  Bind the canonical package to THIS
# checkout's root instead and drop the editable meta-path finder so every
# nested import resolves here too.
#
# Do not gate this on ``_RXYCODE_TEST_CHECKOUT``: pytest-xdist workers inherit
# that env from the parent and would skip binding, then PathFinder-load ``core``
# while ``resolve()`` still returns versioned provider instances.
# ---------------------------------------------------------------------------
if not getattr(sys, "_rxycode_test_checkout_ready", False):
    import importlib
    import types as _types

    _checkout_root = Path(__file__).resolve().parent.parent
    os.environ["RXYCODE_CHECKOUT_ROOT"] = str(_checkout_root)
    os.environ["_RXYCODE_TEST_CHECKOUT"] = str(_checkout_root)
    _editable_finder_types = ("_EditableFinder",)
    sys.meta_path = [
        finder
        for finder in sys.meta_path
        if type(finder).__name__ not in _editable_finder_types
    ]
    _canonical_init = _checkout_root / "__init__.py"
    _canonical = sys.modules.get("RxyCode.RxyCode1_1_0")
    _canonical_file = getattr(_canonical, "__file__", None) if _canonical is not None else None
    _bound_here = False
    if _canonical is not None and _canonical_file:
        try:
            _bound_here = Path(_canonical_file).resolve().parent == _checkout_root
        except OSError:
            _bound_here = False
    if not _bound_here:
        if "RxyCode" not in sys.modules:
            _parent_mod = _types.ModuleType("RxyCode")
            sys.modules["RxyCode"] = _parent_mod
        _canonical = _types.ModuleType("RxyCode.RxyCode1_1_0")
        sys.modules["RxyCode.RxyCode1_1_0"] = _canonical
        sys.modules["RxyCode"].RxyCode1_1_0 = _canonical  # noqa: B010 - dynamic module namespace
        _canonical.__file__ = str(_canonical_init)
        _canonical.__path__ = [str(_checkout_root)]
        _canonical.__package__ = "RxyCode.RxyCode1_1_0"
        if _canonical_init.exists():
            _canonical_source = _canonical_init.read_text(encoding="utf-8-sig")
            exec(compile(_canonical_source, str(_canonical_init), "exec"), _canonical.__dict__)  # noqa: S102
    sys.modules["RxyCode"].RxyCode1_1_0 = _canonical  # noqa: B010 - dynamic module namespace
    _unify = getattr(_canonical, "unify_bare_package_aliases", None)
    if callable(_unify):
        _unify()
    try:
        importlib.import_module("RxyCode.RxyCode1_1_0.core")
        importlib.import_module("RxyCode.RxyCode1_1_0.core.providers")
        importlib.import_module("RxyCode.RxyCode1_1_0.protocol")
        # Install the redirect finder before test modules are collected so
        # ``from core.session`` / ``from protocol.notifications`` are one object.
        importlib.import_module("appserver")
    except ImportError:
        pass
    if callable(_unify):
        _unify()
    sys._rxycode_test_checkout_ready = True  # type: ignore[attr-defined]

import pytest
from langchain_core.messages import AIMessage

# RLI-3: resource paths must be anchored here, never to the process CWD.
REPO_ROOT = Path(__file__).resolve().parent.parent
# RL9: tests re-raise the chat-path fallback. Production leaves this unset.
os.environ["RXYCODE_STRICT_ERRORS"] = "1"


_CANONICAL_MODULE_PREFIX = "RxyCode.RxyCode1_1_0."


def _unified_top_level_packages() -> frozenset[str]:
    """Production list from the checkout root package — not copied.

    ``appserver`` is excluded: ``python -m appserver`` and the canonical
    package are intentionally allowed to be distinct objects.
    """
    pkg = sys.modules.get("RxyCode.RxyCode1_1_0")
    packages = getattr(pkg, "_BARE_PACKAGES", None)
    if packages is None:
        from appserver import _UNIFIED_TOP_LEVEL_PACKAGES

        return _UNIFIED_TOP_LEVEL_PACKAGES
    return frozenset(name for name in packages if name != "appserver")


def _bare_core_module_keys() -> frozenset[str]:
    packages = _unified_top_level_packages()
    return frozenset(
        name for name in sys.modules if name.partition(".")[0] in packages
    )


def _split_identity_keys(names: frozenset[str]) -> list[str]:
    split: list[str] = []
    for name in sorted(names):
        canonical = _CANONICAL_MODULE_PREFIX + name
        bare_mod = sys.modules.get(name)
        can_mod = sys.modules.get(canonical)
        if can_mod is None or bare_mod is not can_mod:
            split.append(name)
    return split


@pytest.fixture(autouse=True)
def _fail_leaked_process_globals(request: pytest.FixtureRequest):
    """Fail the test that leaked CWD or a split-identity sys.modules alias.

    A leaked chdir / split ``sys.modules`` entry shows up as a failure in
    some later unrelated test.  Name the culprit at the moment it leaks.
    Opt out of the CWD check with ``@pytest.mark.allows_cwd_change``.
    Bare keys that resolve to the same object as the canonical spelling
    are not a leak (RL4/RL10); only a real identity split fails.
    """
    before_cwd = os.getcwd()
    before_keys = _bare_core_module_keys()
    yield
    after_cwd = os.getcwd()
    after_keys = _bare_core_module_keys()
    nodeid = request.node.nodeid
    if after_cwd != before_cwd and request.node.get_closest_marker("allows_cwd_change") is None:
        pytest.fail(
            f"{nodeid} leaked process CWD: {before_cwd!r} -> {after_cwd!r}"
        )
    added = after_keys - before_keys
    split = _split_identity_keys(added)
    if split:
        pytest.fail(
            f"{nodeid} added split-identity sys.modules keys: {split}"
        )


#: On CI set to "1". Missing required external tools fail instead of skip,
#: so distribution gates cannot silently report green.
STRICT_TOOLING = os.environ.get("RXYCODE_STRICT_TOOLING") == "1"


def require_tool(name: str, *, reason: str) -> None:
    """Ensure external tool *name* is available.

    In strict mode a missing tool fails the test; locally it skips.
    """
    if shutil.which(name):
        return
    message = f"external tool {name!r} not found (needed for: {reason})"
    if STRICT_TOOLING:
        pytest.fail(message + " — RXYCODE_STRICT_TOOLING=1 forbids skipping")
    pytest.skip(message)


_ISOLATED_ENV_KEYS = (
    "HOME",
    "USERPROFILE",
    "RXYCODE_DATA_DIR",
    "RXYCODE_V2_CONFIG_DIR",
)


def _safe_path_segment(value: str | None, fallback: str) -> str:
    """Return a deterministic filesystem-safe identifier."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", (value or "").strip())
    return cleaned.strip(".-") or fallback


def _create_test_root() -> tuple[Path, bool]:
    """Create a per-invocation test root.

    CI supplies ``RXYCODE_TEST_ROOT`` and a unique lane id so artifacts have a
    stable upload path.  Each xdist worker gets its own leaf directory.  Local
    runs retain the existing random temporary-root behaviour.
    """
    configured = os.environ.get("RXYCODE_TEST_ROOT")
    if not configured:
        return Path(tempfile.mkdtemp(prefix="rxycode-tests-")), True

    base = Path(configured).expanduser().resolve()
    lane = _safe_path_segment(os.environ.get("RXYCODE_TEST_RUN_ID"), "pytest")
    worker = _safe_path_segment(os.environ.get("PYTEST_XDIST_WORKER"), "main")
    root = base / lane / worker
    root.mkdir(parents=True, exist_ok=False)
    return root, False


def pytest_configure(config):
    """Redirect persistent process state before test modules are imported."""
    if hasattr(config, "_rxycode_test_root"):
        return

    root, managed_temp = _create_test_root()
    home = root / "home"
    data_dir = root / "data"
    home.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    # Prevent legacy in-repository data migration into the isolated directory.
    (data_dir / "config.yaml").write_text("{}\n", encoding="utf-8")

    config._rxycode_test_root = root
    config._rxycode_managed_temp = managed_temp
    config._rxycode_saved_env = {
        key: os.environ.get(key) for key in _ISOLATED_ENV_KEYS
    }
    config._rxycode_dont_write_bytecode = sys.dont_write_bytecode
    os.environ.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "RXYCODE_DATA_DIR": str(data_dir),
            "RXYCODE_V2_CONFIG_DIR": str(data_dir),
        }
    )
    sys.dont_write_bytecode = True


def pytest_unconfigure(config):
    root = getattr(config, "_rxycode_test_root", None)
    saved = getattr(config, "_rxycode_saved_env", {})
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    sys.dont_write_bytecode = getattr(
        config, "_rxycode_dont_write_bytecode", sys.dont_write_bytecode
    )
    keep_root = bool(
        os.environ.get("RXYCODE_KEEP_TEST_ARTIFACTS")
        or getattr(config, "_rxycode_test_failed", False)
    )
    if root and getattr(config, "_rxycode_managed_temp", False) and not keep_root:
        shutil.rmtree(root, ignore_errors=True)


def pytest_sessionfinish(session, exitstatus):
    """Preserve the isolated runtime when failures need postmortem evidence."""
    session.config._rxycode_test_failed = exitstatus != 0
    if exitstatus != 0 or os.environ.get("RXYCODE_KEEP_TEST_ARTIFACTS"):
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(
                f"RXYCode test runtime: {session.config._rxycode_test_root}"
            )


def pytest_collection_modifyitems(items):
    """Assign layer markers from the directory layout."""
    layers = {"unit", "integration", "contract", "system", "live"}
    for item in items:
        parts = Path(str(item.fspath)).parts
        try:
            tests_index = parts.index("tests")
        except ValueError:
            continue
        if tests_index + 1 >= len(parts):
            continue
        layer = parts[tests_index + 1]
        if layer in layers:
            item.add_marker(getattr(pytest.mark, layer))
        if layer == "system":
            item.add_marker(pytest.mark.serial)
    unify = getattr(sys.modules.get("RxyCode.RxyCode1_1_0"), "unify_bare_package_aliases", None)
    if callable(unify):
        unify()


# ─── sys.stdout protection ──────────────────────────────────────
# api_server.py lines 10-15 replace sys.stdout/sys.stderr with
# TextIOWrapper on Windows.  When FastAPI's TestClient closes, it can
# close the underlying buffer, leaving all subsequent tests with a
# dead stdout.  This fixture saves the original streams and restores
# them after each test module, preventing the cascade of 174 "I/O
# operation on closed file" errors.

@pytest.fixture(autouse=True, scope="module")
def _protect_stdio():
    """Save and restore sys.stdout/sys.stderr around each test module."""
    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    yield
    sys.stdout = orig_stdout
    sys.stderr = orig_stderr


@pytest.fixture(autouse=True)
def _isolate_process_singletons():
    """Give every test clean process-wide state and restore the prior values."""
    from RxyCode.RxyCode1_1_0.core import tracing
    from RxyCode.RxyCode1_1_0.core import question
    from RxyCode.RxyCode1_1_0.core import session_runtime
    from RxyCode.RxyCode1_1_0.core.safety import approval, audit
    from RxyCode.RxyCode1_1_0.log.monitor import run_monitor
    from RxyCode.RxyCode1_1_0.recovery import circuit_breaker as _circuit_breaker
    from RxyCode.RxyCode1_1_0.utils import tui as tui_mod
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats
    unify = getattr(sys.modules.get("RxyCode.RxyCode1_1_0"), "unify_bare_package_aliases", None)
    if callable(unify):
        unify()

    previous_broker = approval.get_approval_broker()
    previous_question_broker = question.get_question_broker()
    previous_tracer = tracing._tracer
    previous_audit_logger = audit._default_logger
    previous_breaker = _circuit_breaker._default_breaker
    previous_tui = tui_mod._tui_instance
    previous_cwd = Path.cwd()
    api_locks = []
    seen_modules: set[int] = set()
    for module_name in ("RxyCode.RxyCode1_1_0.api_server", "api_server"):
        module = sys.modules.get(module_name)
        if module is None or id(module) in seen_modules:
            continue
        lock = getattr(module, "_chat_lock", None)
        if lock is not None:
            api_locks.append((module, lock))
            module._chat_lock = asyncio.Lock()
            seen_modules.add(id(module))

    token_fields = (
        "input_tokens",
        "output_tokens",
        "cache_hits",
        "cache_misses",
        "context_used",
        "context_max",
        "cache_size",
        "prompt_tokens",
        "cache_hit_tokens",
        "application_cache_hits",
        "application_cache_misses",
        "application_cache_bypasses",
        "_model_name",
        "ttft_ms",
    )
    with token_stats._application_cache_lock:
        previous_token_state = {
            field: deepcopy(getattr(token_stats, field)) for field in token_fields
        }
    with run_monitor._lock:
        previous_monitor_state = (
            deepcopy(run_monitor._counts),
            run_monitor._total_duration_s,
            run_monitor._total_steps,
            run_monitor._total_replans,
            deepcopy(run_monitor._failure_attribution),
            deepcopy(run_monitor._token_usage),
            deepcopy(run_monitor._last_run),
            deepcopy(run_monitor._runs),
            deepcopy(run_monitor._evidence_by_run),
            deepcopy(run_monitor._evidence_totals),
        )

    test_node = os.environ.get("PYTEST_CURRENT_TEST", "test")
    runtime_session_id = (
        "pytest-" + hashlib.sha256(test_node.encode("utf-8")).hexdigest()[:24]
    )
    session_token = session_runtime.bind_session(runtime_session_id)
    approval.set_approval_broker(None)
    question.set_question_broker(None)
    audit._default_logger = None
    _circuit_breaker.reset_breakers()
    token_stats.reset()
    token_stats.reset_ttft()
    token_stats.set_model(None)
    from RxyCode.RxyCode1_1_0.core.catalog import reset_contract_cache

    reset_contract_cache()
    run_monitor.reset()
    test_id = _safe_path_segment(os.environ.get("PYTEST_CURRENT_TEST"), "test")
    tracing.reset_tracer(test_id[:120])
    tui_mod.set_tui(None)
    try:
        yield
    finally:
        tui_mod.set_tui(previous_tui)
        try:
            os.chdir(previous_cwd)
        except OSError:
            pass
        approval.set_approval_broker(previous_broker)
        question.set_question_broker(previous_question_broker)
        session_runtime.clear_session_runtime(runtime_session_id)
        session_runtime.reset_session_binding(session_token)
        tracing._tracer = previous_tracer
        audit._default_logger = previous_audit_logger
        _circuit_breaker._default_breaker = previous_breaker
        for module, lock in api_locks:
            module._chat_lock = lock
        with token_stats._application_cache_lock:
            for field, value in previous_token_state.items():
                setattr(token_stats, field, deepcopy(value))
        with run_monitor._lock:
            (
                run_monitor._counts,
                run_monitor._total_duration_s,
                run_monitor._total_steps,
                run_monitor._total_replans,
                run_monitor._failure_attribution,
                run_monitor._token_usage,
                run_monitor._last_run,
                run_monitor._runs,
                run_monitor._evidence_by_run,
                run_monitor._evidence_totals,
            ) = previous_monitor_state


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    """Isolate filesystem paths and mutable runtime singletons for a test."""
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    data_dir.mkdir()
    workspace.mkdir()
    config_path = data_dir / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("RXYCODE_V2_CONFIG_DIR", str(data_dir))

    # Several legacy modules still use top-level compatibility imports such as
    # ``from config.settings import ...``.  Import them while the repository is
    # on sys.path, then isolate the working directory used by the test itself.
    from RxyCode.RxyCode1_1_0.cache.precise_cache import precise_cache
    from RxyCode.RxyCode1_1_0.cache.semantic_cache import semantic_cache
    from RxyCode.RxyCode1_1_0.core.tracing import reset_tracer

    monkeypatch.chdir(workspace)
    reset_tracer("test-runtime")

    cache_dir = data_dir / "cache"
    cache_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(precise_cache, "_cache_dir", cache_dir)
    monkeypatch.setattr(
        precise_cache, "_index_file", cache_dir / "precise_index.json"
    )
    monkeypatch.setattr(precise_cache, "_index", {})
    monkeypatch.setattr(semantic_cache, "_cache_dir", cache_dir)
    monkeypatch.setattr(
        semantic_cache, "_index_file", cache_dir / "semantic_index.json"
    )
    monkeypatch.setattr(semantic_cache, "_index", [])
    yield SimpleNamespace(
        root=tmp_path,
        data_dir=data_dir,
        workspace=workspace,
        config_path=config_path,
    )


@pytest.fixture
def load_scripted_messages():
    """Load recorded AI messages and substitute explicit fixture variables."""
    response_dir = Path(__file__).parent / "fixtures" / "responses"

    def load(name: str, **values: str) -> list[AIMessage]:
        payload = json.loads((response_dir / name).read_text(encoding="utf-8"))

        def substitute(value):
            if isinstance(value, str):
                return Template(value).safe_substitute(values)
            if isinstance(value, list):
                return [substitute(item) for item in value]
            if isinstance(value, dict):
                return {key: substitute(item) for key, item in value.items()}
            return value

        return [
            AIMessage(
                content=substitute(item.get("content", "")),
                tool_calls=substitute(item.get("tool_calls", [])),
            )
            for item in payload
        ]

    return load
