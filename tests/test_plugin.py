"""PhaseG-B18 plugin market."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from appserver.capabilities import CapabilityService
from appserver.permission import PermissionStore
from appserver.plugin_service import (
    PluginError,
    PluginService,
    bundled_plugin_registry,
    github_archive_url,
    resolve_github_mcp_runtime,
)
from protocol.schema import export_schema


def _plugin_pkg(root: Path, *, name: str = "demo-plug", traversal: str | None = None) -> Path:
    pkg = root / name
    skill = pkg / "skills" / "demo-skill"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("# demo skill\n", encoding="utf-8")
    manifest = {
        "name": name,
        "version": "1.0.0",
        "skills": [{"name": "demo-skill", "path": traversal or "skills/demo-skill"}],
        "commands": [{"name": "demo-cmd", "path": "skills/demo-skill"}],
        "tools": [{"name": "demo-tool", "path": "skills/demo-skill"}],
        "mcp": {"demo-mcp": {"command": "npx", "args": ["-y", "demo"], "connected": False}},
    }
    (pkg / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return pkg


class _PassReview:
    def start(self, **_kwargs):
        return {"review_id": "rev_pass", "status": "passed"}, []


def _service(tmp_path: Path) -> tuple[PluginService, CapabilityService]:
    caps = CapabilityService(
        persistent=False,
        skill_lister=lambda: [],
        mcp_lister=lambda: {},
        review_service=_PassReview(),
    )
    perms = PermissionStore(persistent=False)
    perms.set_profile("workspace_write")
    plugins = PluginService(
        root=tmp_path / "plugins",
        persistent=False,
        capabilities=caps,
        permission_store=perms,
    )
    plugins.attach_to_capabilities()
    return plugins, caps


def test_manifest_rejects_missing_and_traversal(tmp_path: Path) -> None:
    plugins, _caps = _service(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(PluginError) as missing:
        plugins.install(source="local", path=str(empty))
    assert missing.value.code == "PLUGIN_MANIFEST_INVALID"
    bad = _plugin_pkg(tmp_path, name="evil", traversal="../outside")
    with pytest.raises(PluginError) as trav:
        plugins.install(source="local", path=str(bad))
    assert trav.value.code == "PLUGIN_PATH_UNSAFE"
    ver = _plugin_pkg(tmp_path, name="badver")
    payload = json.loads((ver / "plugin.json").read_text(encoding="utf-8"))
    payload["version"] = "v1"
    (ver / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PluginError) as ver_err:
        plugins.install(source="local", path=str(ver))
    assert ver_err.value.code == "PLUGIN_MANIFEST_INVALID"
    mcp_bad = _plugin_pkg(tmp_path, name="badmcp")
    payload = json.loads((mcp_bad / "plugin.json").read_text(encoding="utf-8"))
    payload["mcp"]["demo-mcp"]["args"] = ["../secret"]
    (mcp_bad / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PluginError) as mcp_err:
        plugins.install(source="local", path=str(mcp_bad))
    assert mcp_err.value.code == "PLUGIN_PATH_UNSAFE"
    win = _plugin_pkg(tmp_path, name="winmcp")
    payload = json.loads((win / "plugin.json").read_text(encoding="utf-8"))
    payload["mcp"]["demo-mcp"]["args"] = [r"C:/secret"]
    (win / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PluginError) as win_err:
        plugins.install(source="local", path=str(win))
    assert win_err.value.code == "PLUGIN_PATH_UNSAFE"
    typed = _plugin_pkg(tmp_path, name="badtype")
    payload = json.loads((typed / "plugin.json").read_text(encoding="utf-8"))
    payload["skills"] = 0
    (typed / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PluginError) as type_err:
        plugins.install(source="local", path=str(typed))
    assert type_err.value.code == "PLUGIN_MANIFEST_INVALID"
    slash = _plugin_pkg(tmp_path, name="slashy", traversal="skills\\demo-skill")
    with pytest.raises(PluginError) as slash_err:
        plugins.install(source="local", path=str(slash))
    assert slash_err.value.code == "PLUGIN_PATH_UNSAFE"


def test_install_registers_skill_and_mcp(tmp_path: Path) -> None:
    plugins, caps = _service(tmp_path)
    pkg = _plugin_pkg(tmp_path)
    result = plugins.install(source="local", path=str(pkg))
    assert result["ok"] is True
    rows = {row["capability_id"]: row for row in caps.list()["capabilities"]}
    assert rows["skill:demo-plug.demo-skill"]["installed"] is True
    assert rows["command:demo-plug.demo-cmd"]["kind"] == "command"
    assert rows["tool:demo-plug.demo-tool"]["kind"] == "tool"
    assert "mcp:demo-plug.demo-mcp" in rows
    overlay = plugins.mcp_overlay()["demo-plug.demo-mcp"]
    assert "cwd" not in overlay or str(overlay["cwd"]).startswith(str(Path(result["plugin"]["path"])))
    listed = plugins.list_plugins()["plugins"]
    assert listed[0]["name"] == "demo-plug"
    perms = PermissionStore(persistent=False)
    perms.set_profile("workspace_write")
    caps.set_enabled("tool:demo-plug.demo-tool", True, authorize=True, permission_store=perms)
    job = caps.invoke("tool:demo-plug.demo-tool", permission_store=perms)
    assert job["status"] == "completed"
    assert job["thread_stuck"] is False


def test_toggle_uses_capability_channel(tmp_path: Path) -> None:
    plugins, caps = _service(tmp_path)
    plugins.install(source="local", path=str(_plugin_pkg(tmp_path)))
    toggled = plugins.toggle("demo-plug", False)
    assert toggled["enabled"] is False
    hidden = {row["capability_id"] for row in caps.list()["capabilities"]}
    assert "skill:demo-plug.demo-skill" not in hidden
    assert "tool:demo-plug.demo-tool" not in hidden
    assert "mcp:demo-plug.demo-mcp" not in hidden
    plugins.toggle("demo-plug", True)
    shown = {row["capability_id"]: row for row in caps.list()["capabilities"]}
    assert shown["skill:demo-plug.demo-skill"]["enabled"] is True
    assert shown["tool:demo-plug.demo-tool"]["enabled"] is True
    with pytest.raises(PluginError):
        plugins.toggle("demo-plug", "false")


def test_uninstall_cleanup_and_keep_user_config(tmp_path: Path) -> None:
    plugins, caps = _service(tmp_path)
    plugins.install(source="local", path=str(_plugin_pkg(tmp_path)))
    dest = Path(plugins.list_plugins()["plugins"][0]["path"])
    (dest / "user.json").write_text("{\"theme\":1}", encoding="utf-8")
    plugins.uninstall("demo-plug", keep_user_config=True)
    assert (dest / "user.json").is_file()
    assert "skill:demo-plug.demo-skill" not in {row["capability_id"] for row in caps.list()["capabilities"]}
    plugins.install(source="local", path=str(_plugin_pkg(tmp_path)))
    dest = Path(plugins.list_plugins()["plugins"][0]["path"])
    with pytest.raises(PluginError) as keep_type:
        plugins.uninstall("demo-plug", keep_user_config="false")
    assert keep_type.value.code == "PLUGIN_UNINSTALL_INVALID"
    plugins.uninstall("demo-plug", keep_user_config=False)
    assert not dest.exists()
    assert "skill:demo-plug.demo-skill" not in (caps._data.get("enabled") or {})
    assert "skill:demo-plug.demo-skill" not in (caps._data.get("authorized") or {})


def test_registry_install(tmp_path: Path) -> None:
    _plugin_pkg(tmp_path / "reg", name="from-reg")
    registry = tmp_path / "reg"
    (registry / "registry.json").write_text(
        json.dumps({"plugins": [{"name": "from-reg", "version": "1.0.0", "path": "from-reg"}]}),
        encoding="utf-8",
    )
    plugins, caps = _service(tmp_path)
    plugins.registry = registry
    plugins.install(source="registry", name="from-reg")
    assert any(row["capability_id"] == "skill:from-reg.demo-skill" for row in caps.list()["capabilities"])
    src = _plugin_pkg(tmp_path / "reg-src", name="zip-plug")
    archive = tmp_path / "reg" / "zip-plug.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for file in src.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(src))
    (registry / "registry.json").write_text(
        json.dumps(
            {
                "plugins": [
                    {"name": "from-reg", "version": "1.0.0", "path": "from-reg"},
                    {"name": "zip-plug", "version": "1.0.0", "path": "zip-plug.zip"},
                ]
            }
        ),
        encoding="utf-8",
    )
    plugins.install(source="registry", name="zip-plug")
    assert any(row["name"] == "zip-plug" for row in plugins.list_plugins()["plugins"])
    (registry / "registry.json").write_text(
        json.dumps({"plugins": [{"name": "escaped", "version": "1.0.0", "path": "../outside"}]}),
        encoding="utf-8",
    )
    with pytest.raises(PluginError) as escaped:
        plugins.install(source="registry", name="escaped")
    assert escaped.value.code == "PLUGIN_PATH_UNSAFE"


def test_refuse_symlink_package(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("no", encoding="utf-8")
    pkg = _plugin_pkg(tmp_path, name="linky")
    link = pkg / "skills" / "leak"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink not permitted")
    plugins, _caps = _service(tmp_path)
    with pytest.raises(PluginError) as err:
        plugins.install(source="local", path=str(pkg))
    assert err.value.code == "PLUGIN_PATH_UNSAFE"
    alias = tmp_path / "alias-pkg"
    try:
        alias.symlink_to(pkg, target_is_directory=True)
    except OSError:
        return
    with pytest.raises(PluginError) as src_err:
        plugins.install(source="local", path=str(alias))
    assert src_err.value.code == "PLUGIN_PATH_UNSAFE"


def test_github_archive_url_accepts_owner_repo() -> None:
    assert github_archive_url("owner/repo") == "https://github.com/owner/repo/archive/refs/heads/main.zip"
    assert github_archive_url("https://github.com/owner/repo") == (
        "https://github.com/owner/repo/archive/refs/heads/main.zip"
    )
    assert github_archive_url("https://github.com/owner/repo.git") == (
        "https://github.com/owner/repo/archive/refs/heads/main.zip"
    )
    assert github_archive_url("https://example.com/pkg.zip") == "https://example.com/pkg.zip"


def test_install_bundled_github_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    plugins, caps = _service(tmp_path)
    plugins.registry = bundled_plugin_registry()
    result = plugins.install(source="registry", name="github")
    assert result["ok"] is True
    assert result["plugin"]["name"] == "github"
    assert result["plugin"]["auth"] == "needed"
    rows = {row["capability_id"]: row for row in caps.list()["capabilities"]}
    assert "mcp:github.github" in rows
    assert "skill:github.github" in rows
    overlay = plugins.mcp_overlay()["github.github"]
    assert overlay["command"] == "npx"
    assert overlay["args"] == ["-y", "@modelcontextprotocol/server-github"]
    dest = Path(result["plugin"]["path"])
    assert (dest / "skills" / "github" / "SKILL.md").is_file()
    listed = plugins.list_plugins()["plugins"][0]
    assert listed["auth"] == "needed"
    assert "token" not in listed


def test_resolve_github_mcp_runtime_prefers_official_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "appserver.plugin_service.shutil.which",
        lambda name: "/usr/bin/github-mcp-server" if name == "github-mcp-server" else None,
    )
    command, args = resolve_github_mcp_runtime()
    assert command.endswith("github-mcp-server")
    assert args == ["stdio"]


def test_resolve_github_mcp_runtime_uses_docker_then_npx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "appserver.plugin_service.shutil.which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )
    command, args = resolve_github_mcp_runtime()
    assert command.endswith("docker")
    assert args == [
        "run",
        "-i",
        "--rm",
        "-e",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "ghcr.io/github/github-mcp-server",
    ]
    monkeypatch.setattr(
        "appserver.plugin_service.shutil.which",
        lambda name: "/usr/bin/npx" if name == "npx" else None,
    )
    command, args = resolve_github_mcp_runtime()
    assert command.endswith("npx")
    assert args == ["-y", "@modelcontextprotocol/server-github"]


def test_resolve_github_mcp_runtime_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("appserver.plugin_service.shutil.which", lambda _name: None)
    with pytest.raises(PluginError) as err:
        resolve_github_mcp_runtime()
    assert err.value.code == "PLUGIN_MCP_RUNTIME_MISSING"


def test_github_token_connect_updates_user_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    plugins, _caps = _service(tmp_path)
    plugins.registry = bundled_plugin_registry()
    plugins.install(source="registry", name="github")
    with pytest.raises(PluginError) as already:
        plugins.install(source="registry", name="github")
    assert already.value.code == "PLUGIN_ALREADY_INSTALLED"
    secret = "ghp_test_secret_token"
    second = plugins.install(source="registry", name="github", token=secret)
    assert second["ok"] is True
    assert second["plugin"]["auth"] == "configured"
    dest = Path(second["plugin"]["path"])
    user = json.loads((dest / "user.json").read_text(encoding="utf-8"))
    assert user["token"] == secret
    public = json.dumps(plugins.list_plugins())
    assert secret not in public
    assert "ghp_test" not in public
    assert plugins.list_plugins()["plugins"][0]["auth"] == "configured"


def test_publish_github_mcp_resolves_runtime_and_omits_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_upsert(name, command, args, env):
        captured.update({"name": name, "command": command, "args": args, "env": env})
        return True, "ok"

    monkeypatch.setattr(
        "appserver.plugin_service.shutil.which",
        lambda name: "/bin/github-mcp-server" if name == "github-mcp-server" else None,
    )
    monkeypatch.setattr("tools.mcp_manager.upsert_mcp_server", fake_upsert)
    caps = CapabilityService(
        persistent=False,
        skill_lister=lambda: [],
        mcp_lister=lambda: {},
        review_service=_PassReview(),
    )
    perms = PermissionStore(persistent=False)
    perms.set_profile("workspace_write")
    plugins = PluginService(
        root=tmp_path / "plugins",
        persistent=True,
        capabilities=caps,
        permission_store=perms,
        registry=bundled_plugin_registry(),
    )
    secret = "ghp_should_not_be_in_yaml"
    result = plugins.install(source="registry", name="github", token=secret)
    assert result["ok"] is True
    assert captured["command"] == "/bin/github-mcp-server"
    assert captured["args"] == ["stdio"]
    env = captured.get("env") or {}
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" not in env
    assert secret not in json.dumps(captured, default=str)


def test_github_plugin_token_injected_for_mcp_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp.github_auth import inject_github_plugin_token, read_github_user_token

    user = tmp_path / "user.json"
    user.write_text(json.dumps({"token": "ghp_from_plugin"}), encoding="utf-8")
    assert read_github_user_token(user) == "ghp_from_plugin"
    monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr("config.settings.get_data_dir", lambda: tmp_path)
    (tmp_path / "plugins" / "github").mkdir(parents=True)
    (tmp_path / "plugins" / "github" / "user.json").write_text(
        json.dumps({"token": "ghp_from_plugin"}), encoding="utf-8"
    )
    env: dict[str, str] = {}
    inject_github_plugin_token(env, "github")
    assert env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_from_plugin"
    other: dict[str, str] = {}
    inject_github_plugin_token(other, "fetch")
    assert other == {}


def test_schema_has_plugin_methods() -> None:
    defs = export_schema()["$defs"]
    assert "PluginListRequest" in defs
    assert "PluginInstallRequest" in defs
    assert "PluginUninstallRequest" in defs
    assert "PluginToggleRequest" in defs
    refs = [item.get("$ref") for item in export_schema()["$defs"]["ClientRequest"]["oneOf"]]
    assert "#/$defs/PluginListRequest" in refs
    assert "#/$defs/PluginInstallRequest" in refs
    assert Path("appserver/handlers").exists() is False
    from pydantic import ValidationError
    from protocol.requests import PluginToggleRequest

    with pytest.raises(ValidationError):
        PluginToggleRequest.model_validate({"name": "x", "enabled": "false"})


@pytest.mark.asyncio
async def test_protocol_plugin_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from appserver.server import AppServer

    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    server._permissions.set_profile("workspace_write")
    pkg = _plugin_pkg(tmp_path)
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "plugin/install",
            "params": {"source": "local", "path": str(pkg)},
        }
    )
    installed = next(item["result"] for item in sent if item.get("id") == 1)
    assert installed["ok"] is True
    sent.clear()
    await server._dispatch({"jsonrpc": "2.0", "id": 2, "method": "plugin/list", "params": {}})
    listed = next(item["result"] for item in sent if item.get("id") == 2)
    assert listed["plugins"]
    sent.clear()
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 3, "method": "plugin/toggle", "params": {"name": "demo-plug", "enabled": False}}
    )
    toggled = next(item["result"] for item in sent if item.get("id") == 3)
    assert toggled["enabled"] is False
    sent.clear()
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 4, "method": "plugin/uninstall", "params": {"name": "demo-plug"}}
    )
    removed = next(item["result"] for item in sent if item.get("id") == 4)
    assert removed["removed"] is True


@pytest.mark.asyncio
async def test_protocol_github_token_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    from appserver.server import AppServer

    monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    server._permissions.set_profile("workspace_write")
    server._plugins.registry = bundled_plugin_registry()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "plugin/install",
            "params": {"source": "registry", "name": "github"},
        }
    )
    installed = next(item["result"] for item in sent if item.get("id") == 1)
    assert installed["plugin"]["auth"] == "needed"
    sent.clear()
    secret = "ghp_protocol_secret"
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "plugin/install",
            "params": {"source": "registry", "name": "github", "token": secret},
        }
    )
    connected = next(item["result"] for item in sent if item.get("id") == 2)
    assert connected["plugin"]["auth"] == "configured"
    assert secret not in json.dumps(sent)
