"""RxyCode CLI and Ink frontend launcher."""

import sys
import os

# CRITICAL: Set UTF-8 encoding BEFORE any other imports/output.
# On Windows, stdout may default to cp1252 when piped (e.g. CI),
# causing UnicodeEncodeError on Chinese help text.
if sys.platform == "win32":
    try:
        os.system("chcp 65001 >nul 2>&1")
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        ctypes.windll.kernel32.SetConsoleCP(65001)
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)

        # Enable VT sequences so 24-bit pink / Unicode blocks match modern terminals.
        _ENABLE_PROCESSED_OUTPUT = 0x0001
        _ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        _stdout = ctypes.windll.kernel32.GetStdHandle(-11)
        _mode = wintypes.DWORD()
        if ctypes.windll.kernel32.GetConsoleMode(_stdout, ctypes.byref(_mode)):
            ctypes.windll.kernel32.SetConsoleMode(
                _stdout,
                _mode.value | _ENABLE_PROCESSED_OUTPUT | _ENABLE_VIRTUAL_TERMINAL_PROCESSING,
            )

        # Prefer Consolas so U+2588 █ is single-cell (CJK Ambiguous Width
        # on raster fonts shatters the RXYCODE wordmark in cmd.exe).
        class _COORD(ctypes.Structure):
            _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

        class _CONSOLE_FONT_INFOEX(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.ULONG),
                ("nFont", wintypes.DWORD),
                ("dwFontSize", _COORD),
                ("FontFamily", wintypes.UINT),
                ("FontWeight", wintypes.UINT),
                ("FaceName", wintypes.WCHAR * 32),
            ]

        _font = _CONSOLE_FONT_INFOEX()
        _font.cbSize = ctypes.sizeof(_CONSOLE_FONT_INFOEX)
        _font.dwFontSize.Y = 16
        _font.FontFamily = 54  # FF_MODERN | FIXED_PITCH-ish TrueType
        _font.FontWeight = 400
        _font.FaceName = "Consolas"
        ctypes.windll.kernel32.SetCurrentConsoleFontEx(_stdout, False, ctypes.byref(_font))
    except Exception:
        pass
# Reconfigure std streams to UTF-8 regardless of console vs pipe.
# reconfigure() is preferred (in-place), but fall back to wrapping
# the underlying buffer if it fails or is unavailable.
import io as _io
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        try:
            _buf = _stream.buffer
            _new = _io.TextIOWrapper(_buf, encoding="utf-8", errors="replace", line_buffering=_stream.line_buffering)
            if _stream is sys.stdout:
                sys.stdout = _new
            else:
                sys.stderr = _new
        except Exception:
            pass

import click

from . import __version__


def _find_available_port(start_port: int = 8765, max_tries: int = 16) -> int:
    """Find an available port starting from start_port.

    The embedded API is loopback-only, so probe the exact address it uses.
    """
    import socket
    for offset in range(max_tries):
        port = start_port + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No available port found in range {start_port}-{start_port + max_tries - 1}")


def _wait_for_api_ready(port: int, token: str, timeout: float = 30.0) -> bool:
    import urllib.request
    import time as _time

    deadline = _time.time() + timeout
    url = f"http://127.0.0.1:{port}/status"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    while _time.time() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        _time.sleep(0.5)
    return False


def _frontend_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "frontend")


def _opentui_app_dir() -> str:
    return os.path.join(_frontend_dir(), "opentui-app")


def _opentui_ready() -> bool:
    """True when the isolated OpenTUI package looks installable/runnable."""
    app_dir = _opentui_app_dir()
    return os.path.exists(os.path.join(app_dir, "package.json")) and os.path.exists(
        os.path.join(app_dir, "src", "index.tsx")
    )


def _bun_executable():
    """Locate Bun on PATH or in the default install location (~/.bun/bin)."""
    import shutil
    from pathlib import Path

    found = shutil.which("bun")
    if found:
        return found

    home = Path.home()
    bun_install = (os.environ.get("BUN_INSTALL") or "").strip()
    candidates = []
    if bun_install:
        candidates.append(Path(bun_install) / "bin" / "bun")
        candidates.append(Path(bun_install) / "bin" / "bun.exe")
    candidates.extend(
        [
            home / ".bun" / "bin" / "bun",
            home / ".bun" / "bin" / "bun.exe",
        ]
    )
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def _install_bun_runtime() -> str | None:
    """Best-effort install of Bun via the official installer. Returns bun path."""
    import shutil
    import subprocess
    import tempfile
    import urllib.request
    from pathlib import Path

    if (os.environ.get("RXYCODE_SKIP_BUN_INSTALL") or "").strip() == "1":
        return None

    installer_url = (
        "https://bun.sh/install.ps1"
        if os.name == "nt"
        else "https://bun.sh/install"
    )
    try:
        from .log.logger import get_logger

        get_logger().info("Bun missing; downloading official installer", extra={"url": installer_url})
    except Exception:
        pass

    with tempfile.TemporaryDirectory(prefix="rxycode-bun-") as tmp:
        if os.name == "nt":
            script = Path(tmp) / "install.ps1"
            urllib.request.urlretrieve(installer_url, script)
            ps = shutil.which("powershell") or shutil.which("pwsh")
            if not ps:
                return None
            proc = subprocess.run(
                [
                    ps,
                    "-NoLogo",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ],
                check=False,
            )
        else:
            script = Path(tmp) / "install.sh"
            urllib.request.urlretrieve(installer_url, script)
            proc = subprocess.run(
                ["sh", str(script)],
                check=False,
            )
        if proc.returncode != 0:
            return None
    return _bun_executable()


def _ensure_bun(*, required: bool) -> str | None:
    """Return a Bun executable, optionally installing it when missing."""
    found = _bun_executable()
    if found:
        return found
    found = _install_bun_runtime()
    if found:
        return found
    if required:
        raise click.ClickException(
            "Bun is required by the OpenTUI frontend but was not found on PATH "
            "(and auto-install failed). Install Bun from https://bun.sh "
            "or set RXYCODE_TUI=ink. Set RXYCODE_SKIP_BUN_INSTALL=1 to skip auto-install."
        )
    return None


def _ensure_opentui_dependencies(app_dir: str, bun_exe: str) -> None:
    """Run ``bun install`` once when packaged OpenTUI lacks node_modules."""
    import subprocess
    from pathlib import Path

    root = Path(app_dir)
    marker = root / "node_modules" / "@opentui" / "react"
    if marker.exists():
        return
    try:
        from .log.logger import get_logger

        get_logger().info("Installing OpenTUI dependencies", extra={"cwd": app_dir})
    except Exception:
        pass
    proc = subprocess.run(
        [bun_exe, "install"],
        cwd=str(root),
        check=False,
    )
    if proc.returncode != 0:
        raise click.ClickException(
            f"bun install failed in {app_dir} (exit {proc.returncode}). "
            "Install Bun packages manually or set RXYCODE_TUI=ink."
        )


def _resolve_tui_backend() -> str:
    """Pick Ink vs OpenTUI.

    Env ``RXYCODE_TUI=ink`` forces Ink; ``RXYCODE_TUI=opentui`` forces OpenTUI
    (auto-installs Bun when possible; errors if Bun/app still missing).

    Default: OpenTUI when ``frontend/opentui-app`` is present and Bun is
    available or can be auto-installed. Else Ink.
    """
    preference = (os.environ.get("RXYCODE_TUI") or "").strip().lower()
    ready = _opentui_ready()

    if preference == "ink":
        return "ink"
    if preference == "opentui":
        if not ready:
            raise click.ClickException(
                "RXYCODE_TUI=opentui requires frontend/opentui-app (package.json + "
                "src/index.tsx), but it is missing. Set RXYCODE_TUI=ink to use Ink."
            )
        _ensure_bun(required=True)
        return "opentui"
    if preference and preference not in ("ink", "opentui", "auto", ""):
        raise click.ClickException(
            f"Unknown RXYCODE_TUI={preference!r}. Use 'ink', 'opentui', or unset."
        )
    if ready and _ensure_bun(required=False):
        return "opentui"
    return "ink"


def _start_embedded_api(port: int):
    """Start the loopback API and return (port, token, env overlays for the TUI)."""
    import secrets
    import threading
    import time
    from .log.logger import get_logger

    _log = get_logger()
    port = _find_available_port(port)
    api_token = secrets.token_urlsafe(32)
    api_error: list[str] = []

    def run_api():
        # Suppress uvicorn noise only — do not disable the rxycode logger.
        import logging

        logging.getLogger("uvicorn").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        try:
            from .api_server import run_api_server

            run_api_server(port=port, token=api_token)
        except Exception as e:
            api_error.append(str(e))

    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    _log.info("API server thread started", extra={"port": port})

    api_start = time.time()
    api_ready = _wait_for_api_ready(port, token=api_token, timeout=30.0)
    if not api_ready:
        _log.error("API server timeout", extra={"port": port, "timeout_sec": 30})
        reason = f" Reason: {api_error[0]}" if api_error else ""
        raise click.ClickException(
            f"API server failed to start on port {port} within 30s.{reason}"
        )

    print(f"RxyCode API ready at http://127.0.0.1:{port}")
    _log.info(
        "API server ready",
        extra={"port": port, "elapsed_sec": f"{time.time() - api_start:.1f}"},
    )

    env = os.environ.copy()
    env["RXYCODE_API_PORT"] = str(port)
    # Point the TUI at the exact IPv4 loopback URL the API binds to, so a
    # "localhost" -> IPv6 ::1 resolution on the user's machine can't cause
    # ECONNREFUSED ("error connect").
    env["RXYCODE_API_URL"] = f"http://127.0.0.1:{port}"
    env["RXYCODE_API_TOKEN"] = api_token
    return port, api_token, env


def _launch_ink_tui(model, port):
    """Launch the TypeScript + Ink TUI."""
    import shutil
    import subprocess
    from .log.logger import get_logger

    _log = get_logger()
    frontend_dir = _frontend_dir()

    package_json = os.path.join(frontend_dir, "package.json")
    dist_entry = os.path.join(frontend_dir, "dist", "index.js")
    if not os.path.exists(package_json) or not os.path.exists(dist_entry):
        raise click.ClickException(
            "Ink frontend runtime is missing. Reinstall RxyCode or run "
            "'npm run build' in the frontend directory."
        )

    node_exe = shutil.which("node")
    if not node_exe:
        raise click.ClickException(
            "Node.js 20 or newer is required by the Ink frontend but was not "
            "found on PATH."
        )

    port, _api_token, env = _start_embedded_api(port)
    if model:
        env["RXYCODE_MODEL"] = str(model)

    _log.info(
        "Launching Ink TUI",
        extra={"frontend_dir": frontend_dir, "port": port, "node": node_exe},
    )

    proc = None
    try:
        proc = subprocess.Popen(
            [node_exe, dist_entry],
            cwd=frontend_dir,
            env=env,
            shell=False,
        )
        _log.info(
            "Ink TUI started",
            extra={"pid": proc.pid, "node": node_exe, "entry": dist_entry},
        )
        returncode = proc.wait()
        _log.info("Ink TUI exited", extra={"returncode": returncode})
        if returncode != 0:
            raise click.ClickException(
                f"Ink frontend exited with status {returncode}."
            )
    except KeyboardInterrupt:
        if proc:
            proc.terminate()
            proc.wait(timeout=5)
        _log.warn("User interrupted (Ctrl-C)")
    except click.ClickException:
        raise
    except Exception as e:
        _log.error(f"Ink TUI launch failed: {e}", exc_info=True)
        raise click.ClickException(f"Ink frontend failed to launch: {e}") from e
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            _log.info("Ink TUI terminated in finally")


def _launch_opentui_tui(model, port):
    """Launch the Bun + OpenTUI dual-entry shell (ScrollBox + native textarea)."""
    import subprocess
    from .log.logger import get_logger

    _log = get_logger()
    bun_exe = _ensure_bun(required=True)
    app_dir = _opentui_app_dir()
    if not _opentui_ready():
        raise click.ClickException(
            "OpenTUI frontend is missing. Expected frontend/opentui-app with "
            "package.json and src/index.tsx."
        )
    _ensure_opentui_dependencies(app_dir, bun_exe)

    port, _api_token, env = _start_embedded_api(port)
    if model:
        env["RXYCODE_MODEL"] = str(model)

    _log.info(
        "Launching OpenTUI",
        extra={"opentui_dir": app_dir, "port": port, "bun": bun_exe},
    )

    proc = None
    try:
        proc = subprocess.Popen(
            [bun_exe, "run", "src/index.tsx"],
            cwd=app_dir,
            env=env,
            shell=False,
        )
        _log.info(
            "OpenTUI started",
            extra={"pid": proc.pid, "bun": bun_exe, "cwd": app_dir},
        )
        returncode = proc.wait()
        _log.info("OpenTUI exited", extra={"returncode": returncode})
        if returncode != 0:
            raise click.ClickException(
                f"OpenTUI frontend exited with status {returncode}."
            )
    except KeyboardInterrupt:
        if proc:
            proc.terminate()
            proc.wait(timeout=5)
        _log.warn("User interrupted (Ctrl-C)")
    except click.ClickException:
        raise
    except Exception as e:
        _log.error(f"OpenTUI launch failed: {e}", exc_info=True)
        raise click.ClickException(f"OpenTUI frontend failed to launch: {e}") from e
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            _log.info("OpenTUI terminated in finally")


def _launch_tui(model, port):
    """Route to OpenTUI or Ink based on RXYCODE_TUI / Bun availability."""
    from .log.logger import get_logger

    _log = get_logger()
    backend = _resolve_tui_backend()
    _log.info("TUI backend selected", extra={"backend": backend})
    if backend == "opentui":
        _launch_opentui_tui(model, port)
    else:
        _launch_ink_tui(model, port)


def _resolve_model_label(model):
    """#3: Resolve the startup model label from config instead of the literal
    'default'. When the CLI --model is given we use it verbatim; otherwise we
    read the active model's model_name from the config so the startup log shows
    the real model (e.g. deepseek-v4-flash) rather than a misleading 'default'.
    """
    if model:
        return model
    try:
        from .config.settings import load_config
        cfg = load_config()
        active = cfg.get("active_model", "")
        models = cfg.get("models", {})
        if active and active in models:
            return models[active].get("model_name", active)
        for m in models.values():
            return m.get("model_name", active or "default")
    except Exception:
        pass
    return "default"


@click.group(invoke_without_command=True)
@click.pass_context
@click.option("--model", "-m", default=None, help="Model name to use")
@click.option("--api", is_flag=True, default=False, help="Start API server only")
@click.option("--api-port", default=8765, help="API server port")
@click.option("--log-level", default="INFO", help="日志级别: DEBUG/INFO/WARN/ERROR")
@click.option("--print-logs", is_flag=True, default=False, help="同时将日志输出到 stderr")
@click.version_option(version=__version__, prog_name="RxyCode")
def cli(ctx, model, api, api_port, log_level, print_logs):
    """RxyCode - General-Purpose AI Agent"""
    if ctx.invoked_subcommand is None:
        # Non-TTY guard: Ink requires an interactive terminal.
        # Must run before setup_logging to avoid hangs in CI pipes.
        # On Windows PowerShell, isatty() may return True even when piped,
        # so also check the CI environment variable as a fallback.
        # Use os.write + os._exit for maximum reliability in CI pipes.
        if not api and (
            not sys.stdin.isatty()
            or not sys.stdout.isatty()
            or os.getenv("GITHUB_ACTIONS") == "true"
            or os.getenv("CI") == "true"
        ):
            _msg = (
                "RxyCode requires an interactive terminal (TTY) to run the "
                "Ink frontend. Use --api for headless/server mode.\n"
            )
            os.write(2, _msg.encode("utf-8"))
            os._exit(1)

        # 初始化应用级日志（对标 opencode 日志模式，key=value 结构化格式）
        from .log.logger import setup_logging
        _log = setup_logging(level=log_level, print_logs=print_logs)

        if api:
            _log.info("RxyCode started", extra={"mode": "api", "port": api_port})
            from .api_server import run_api_server
            import secrets
            api_token = secrets.token_urlsafe(32)
            # Standalone API clients need an explicit one-time handoff. Keep
            # the credential on the controlling terminal, never in the logger
            # or command-line arguments/process list.
            click.echo(f"RxyCode API bearer token: {api_token}", err=True)
            run_api_server(port=api_port, token=api_token)
        else:
            backend = _resolve_tui_backend()
            _log.info(
                "RxyCode started",
                extra={
                    "mode": backend,
                    "model": _resolve_model_label(model),
                    "port": api_port,
                },
            )
            _launch_tui(model, api_port)

        _log.info("RxyCode exited")
        # 确保日志写入磁盘（进程退出前 flush 所有 handlers）
        for h in _log.handlers:
            try:
                h.flush()
            except Exception:
                pass


@cli.command()
@click.argument("subcommand", default="list")
@click.argument("name", default="")
def config(subcommand, name):
    """Manage model configuration."""
    from .config import model_manager
    from .config.settings import load_config

    if subcommand == "list":
        cfg = load_config()
        models = cfg.get("models", {})
        active = cfg.get("active_model", "")
        for name, mcfg in models.items():
            status = " (active)" if name == active else ""
            print(f"{name}{status} - {mcfg.get('model_name', '')} @ {mcfg.get('base_url', '')}")
    elif subcommand == "test-model":
        if not name:
            print("Usage: RxyCode config test-model <name>")
            return
        result = model_manager.test_model_connection(name)
        if result["success"]:
            print(f"Connected ({result['elapsed']}s)")
        else:
            print(f"Failed: {result['error']}")
    elif subcommand == "set-active":
        if not name:
            print("Usage: RxyCode config set-active <name>")
            return
        if model_manager.set_active_model(name):
            print(f"Active model: {name}")
        else:
            print(f"Model '{name}' not found")
    elif subcommand == "remove":
        if not name:
            print("Usage: RxyCode config remove <name>")
            return
        if model_manager.remove_model(name):
            print(f"Removed: {name}")
        else:
            print(f"Model '{name}' not found")
    else:
        print("Subcommands: list, test-model, set-active, remove")


if __name__ == "__main__":
    cli()
