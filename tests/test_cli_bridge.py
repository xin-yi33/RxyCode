"""PhaseG-B14 CLI-Hub. cli: ids are parameters, not registry tools."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from appserver.capabilities import CapabilityService
from appserver.cli_hub_service import (
    AGENT_TOOLS,
    GENERATE_LADDER,
    INSTALL_GUIDE,
    CliHubError,
    CliHubService,
    venv_python,
)
from appserver.server import AppServer
from core.prefix_profile import PrefixProfile, digest_tools
from protocol.schema import export_schema
from scripts.cli_venv import venv_python as script_venv_python
from tools.cli_bridge import AGENT_TOOLS as BRIDGE_TOOLS

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cli_hub_demo"


def _registry() -> dict:
    return {
        "demo": {
            "source": "cli-hub",
            "schema": {"name": "cli:demo", "args": ["text"]},
            "module": "cli_hub_demo",
            "install": {"kind": "local", "path": str(FIXTURE)},
        }
    }


def _hub(tmp_path: Path) -> CliHubService:
    return CliHubService(root=tmp_path, registry=_registry())


def _identity(tools: list) -> str:
    return PrefixProfile(
        kind="agent",
        session_id="s",
        provider="p",
        model="m",
        thinking_enabled=False,
        thinking_effort=None,
        tools_digest=digest_tools(tools),
        s1_digest="x",
        system_template_version="1",
        prompt_variant="default",
    ).identity()


def test_list_install_launch_isolated(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    listed = hub.list_software()
    assert listed["software"][0]["id"] == "cli:demo"
    assert listed["software"][0]["installed"] is False
    assert listed["agent_tools"] == list(AGENT_TOOLS)
    installed = hub.install("demo")
    assert installed["isolated"] is True
    assert Path(installed["venv"]).is_dir()
    assert installed["pip"]["kind"] == "local"
    assert installed["pip"]["pip_argv"][0] == installed["python"]
    assert installed["pip"]["pip_argv"][1:3] == ["-m", "pip"]
    assert Path(installed["python"]).resolve() != Path(__import__("sys").executable).resolve()
    py = Path(installed["python"])
    probe = __import__("subprocess").run(
        [str(py), "-c", "import cli_hub_demo; print(cli_hub_demo.__version__)"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0
    assert "0.1.0" in probe.stdout
    host = __import__("subprocess").run(
        [__import__("sys").executable, "-c", "import cli_hub_demo"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert host.returncode != 0
    launched = hub.launch("cli:demo", ["hello"])
    assert launched["id"] == "cli:demo"
    assert launched["source"] == "cli-hub"
    assert launched["exit_code"] == 0
    assert "hello" in launched["stdout"]
    assert "cli-hub-demo" in launched["stdout"]
    assert hub.cli_run("demo", ["x"])["ok"] is True
    removed = hub.uninstall("demo")
    assert removed["removed"] is True


def test_start_stop_lifecycle(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    hub.install("demo")
    started = hub.start("demo")
    assert started["status"] == "running"
    assert started["pid"]
    with pytest.raises(CliHubError) as already:
        hub.start("demo")
    assert already.value.code == "CLI_ALREADY_RUNNING"
    stopped = hub.stop("demo")
    assert stopped["status"] == "stopped"
    hub.uninstall("demo")


def test_missing_software_and_not_installed(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    with pytest.raises(CliHubError) as missing:
        hub.install("ghost")
    assert missing.value.code == "CLI_NOT_FOUND"
    with pytest.raises(CliHubError) as not_in:
        hub.launch("demo")
    assert not_in.value.code == "CLI_NOT_INSTALLED"
    assert INSTALL_GUIDE in not_in.value.message
    with pytest.raises(CliHubError) as start_missing:
        hub.start("demo")
    assert start_missing.value.code == "CLI_NOT_INSTALLED"
    assert INSTALL_GUIDE in start_missing.value.message
    stopped = hub.stop("demo")
    assert stopped["status"] == "stopped"


def test_name_freeze_and_registry_priority(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    first = hub.install("demo", source="self-generated")
    assert first["source"] == "cli-hub"
    assert first["decision"]["priority"] == 1
    with pytest.raises(CliHubError) as frozen:
        hub.install("demo")
    assert frozen.value.code == "CLI_NAME_FROZEN"
    hub.uninstall("demo")


def test_decide_cc_ladder(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    assert hub.decide("demo")["action"] == "cli-hub-install"
    assert hub.decide("private", has_source=True)["priority"] == 2
    assert hub.decide("sdk-only", has_sdk=True)["priority"] == 3
    rejected = hub.decide("closed")
    assert rejected["action"] == "reject"
    assert rejected["code"] == "CLI_NOT_ADOPTED"


def test_generate_failure_interface(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    record = hub.record_generate_failure("new-app", "generate", "schema invalid")
    assert record["stage"] == "generate"
    assert record["next_step"] == "refine"
    hub.record_generate_failure("new-app", "refine", "still invalid")
    hub.record_generate_failure("new-app", "handwritten-wrapper", "fallback")
    listed = hub.list_generate_failures("new-app")
    assert listed["ladder"] == list(GENERATE_LADDER)
    assert len(listed["failures"]) == 3
    assert listed["failures"][-1]["next_step"] is None
    with pytest.raises(CliHubError) as bad:
        hub.record_generate_failure("new-app", "invented", "nope")
    assert bad.value.code == "CLI_LADDER_INVALID"


def test_registry_cache_ttl_fallback(tmp_path: Path) -> None:
    hub = CliHubService(root=tmp_path)
    hub.registry_url = "http://127.0.0.1:1/missing.json"
    hub._write_json(
        hub.cache_path,
        {"fetched_at": time.time(), "software": {"cached": {"source": "cli-hub"}}},
    )
    fresh = hub.fetch_registry()
    assert fresh["from_cache"] is True
    assert "cached" in fresh["software"]
    hub._write_json(
        hub.cache_path,
        {"fetched_at": 1.0, "software": {"stale": {"source": "cli-hub"}}},
    )
    stale = hub.fetch_registry()
    assert stale.get("stale") is True
    assert "stale" in stale["software"]


def test_cli_prefix_not_in_registry() -> None:
    from tools import registry

    text = Path(registry.__file__).read_text(encoding="utf-8")
    assert "cli:" not in text
    names = getattr(registry, "TOOL_NAMES", None) or getattr(registry, "TOOLS", None)
    if isinstance(names, dict):
        assert not any(str(key).startswith("cli:") for key in names)


def test_n13_prefix_identity_stable_across_install_counts(tmp_path: Path) -> None:
    names = {f"sw{i}": {"source": "cli-hub", "schema": {"name": f"cli:sw{i}"}} for i in range(20)}
    hub = CliHubService(root=tmp_path, registry=names)
    tools = hub.agent_tools()
    assert [tool.name for tool in tools] == ["cli_list", "cli_run"]
    assert [tool.name for tool in BRIDGE_TOOLS] == ["cli_list", "cli_run"]
    before = _identity(tools)
    installed = hub._read_json(hub.installed_path)
    installed["cli:sw0"] = {"installed": True, "source": "cli-hub"}
    hub._write_json(hub.installed_path, installed)
    one = _identity(hub.agent_tools())
    for i in range(20):
        installed[f"cli:sw{i}"] = {"installed": True, "source": "cli-hub"}
    hub._write_json(hub.installed_path, installed)
    twenty = _identity(hub.agent_tools())
    assert before == one == twenty
    from tools import registry

    assert "cli:" not in Path(registry.__file__).read_text(encoding="utf-8")


def test_launch_start_fail_when_venv_python_missing(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    hub._write_json(
        hub.installed_path,
        {
            "cli:demo": {
                "installed": True,
                "python": str(tmp_path / "missing-python.exe"),
                "venv": str(tmp_path / "venv" / "demo"),
                "source": "cli-hub",
            }
        },
    )
    with pytest.raises(CliHubError) as launch_err:
        hub.launch("demo")
    assert launch_err.value.code == "CLI_VENV_FAILED"
    assert INSTALL_GUIDE in launch_err.value.message
    with pytest.raises(CliHubError) as start_err:
        hub.start("demo")
    assert start_err.value.code == "CLI_VENV_FAILED"
    assert INSTALL_GUIDE in start_err.value.message


def test_venv_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    import appserver.cli_hub_service as hubmod
    import scripts.cli_venv as scriptmod

    monkeypatch.setattr(hubmod.os, "name", "nt")
    assert "Scripts" in str(hubmod.venv_python(Path("env")))
    assert str(hubmod.venv_python(Path("env"))).endswith("python.exe")
    monkeypatch.setattr(hubmod.os, "name", "posix")
    posix_path = hubmod.venv_python(Path("env"))
    assert str(posix_path).replace("\\", "/").endswith("bin/python")
    monkeypatch.setattr(scriptmod.os, "name", "nt")
    assert str(script_venv_python(Path("x"))).endswith("python.exe")
    monkeypatch.setattr(scriptmod.os, "name", "posix")
    assert str(scriptmod.venv_python(Path("x"))).replace("\\", "/").endswith("bin/python")


def test_schema_has_cli_methods() -> None:
    defs = export_schema()["$defs"]
    for name in (
        "CliListRequest",
        "CliInstallRequest",
        "CliLaunchRequest",
        "CliUninstallRequest",
        "CliStartRequest",
        "CliStopRequest",
        "CliDecideRequest",
        "CliRecordFailureRequest",
    ):
        assert name in defs


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()


def test_source_tags_enter_capability_metadata(tmp_path: Path) -> None:
    registry = {
        "demo": {
            "source": "cli-hub",
            "schema": {"name": "cli:demo"},
            "module": "cli_hub_demo",
            "install": {"kind": "local", "path": str(FIXTURE)},
        },
        "hand": {"source": "self-generated", "schema": {"name": "cli:hand"}},
        "core": {"source": "builtin", "schema": {"name": "cli:core"}},
    }
    hub = CliHubService(root=tmp_path, registry=registry)
    meta = hub.tool_metadata()
    sources = {row["id"]: row["source"] for row in meta["tools"]}
    assert sources["tool:cli_list"] == "builtin"
    assert sources["tool:cli_run"] == "builtin"
    assert sources["cli:demo"] == "cli-hub"
    assert sources["cli:hand"] == "self-generated"
    assert sources["cli:core"] == "builtin"
    caps = CapabilityService(persistent=False, cli_lister=hub.tool_metadata)
    rows = {row["capability_id"]: row for row in caps.list(kind="cli")["capabilities"]}
    assert rows["tool:cli_list"]["source"] == "builtin"
    assert rows["cli:demo"]["tool_metadata"]["source"] == "cli-hub"
    assert rows["cli:hand"]["source"] == "self-generated"
    assert rows["cli:core"]["source"] == "builtin"


def test_structured_errors_include_install_guide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hub = _hub(tmp_path)
    with pytest.raises(CliHubError) as missing:
        hub.install("ghost")
    assert missing.value.code == "CLI_NOT_FOUND"
    assert "cli/install" in missing.value.message

    def boom(*_a, **_k):
        raise RuntimeError("no venv")

    monkeypatch.setattr("appserver.cli_hub_service.venv.create", boom)
    with pytest.raises(CliHubError) as venv_failed:
        hub.install("demo")
    assert venv_failed.value.code == "CLI_VENV_FAILED"
    assert INSTALL_GUIDE in venv_failed.value.message

    monkeypatch.undo()
    hub = _hub(tmp_path)

    def timeout(self, argv, *, timeout_s, extra_env=None):
        raise CliHubError("CLI_TIMEOUT", f"{argv[:3]} timed out; {INSTALL_GUIDE}")

    monkeypatch.setattr(CliHubService, "_run_venv", timeout)
    with pytest.raises(CliHubError) as timed:
        hub.install("demo")
    assert timed.value.code == "CLI_TIMEOUT"
    assert INSTALL_GUIDE in timed.value.message


@pytest.mark.asyncio
async def test_protocol_cli_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    server._cli_hub = CliHubService(root=tmp_path, registry=_registry())
    server._capabilities = CapabilityService(persistent=False, cli_lister=server._cli_hub.tool_metadata)
    await server._dispatch({"jsonrpc": "2.0", "id": 1, "method": "cli/list", "params": {}})
    listed = next(item["result"] for item in sent if item.get("id") == 1)
    assert listed["software"][0]["id"] == "cli:demo"
    sent.clear()
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 2, "method": "cli/decide", "params": {"name": "demo"}}
    )
    decided = next(item["result"] for item in sent if item.get("id") == 2)
    assert decided["priority"] == 1
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "cli/record_failure",
            "params": {"name": "new", "stage": "generate", "reason": "bad schema"},
        }
    )
    recorded = next(item["result"] for item in sent if item.get("id") == 3)
    assert recorded["next_step"] == "refine"
    sent.clear()
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 4, "method": "cli/install", "params": {"name": "ghost"}}
    )
    err = next(item["error"] for item in sent if item.get("id") == 4)
    assert err["data"]["error_code"] == "CLI_NOT_FOUND"
    await server._dispatch({"jsonrpc": "2.0", "id": 5, "method": "capabilities/list", "params": {"kind": "cli"}})
    caps = next(item["result"] for item in sent if item.get("id") == 5)
    sources = {row["capability_id"]: row["source"] for row in caps["capabilities"]}
    assert sources["tool:cli_list"] == "builtin"
    assert sources["cli:demo"] == "cli-hub"
