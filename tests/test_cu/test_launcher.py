"""Computer Use stdio command selection."""

from __future__ import annotations

from RxyCode.RxyCode1_1_0.core.cu import launcher


def test_cmd_and_bat_shims_are_not_stdio_commands():
    assert launcher._is_usable_command(r"D:\nodejs\open-computer-use-mcp.CMD") is False
    assert launcher._is_usable_command(r"D:\nodejs\open-computer-use.bat") is False
    assert launcher._is_usable_command(r"D:\nodejs\open-computer-use.ps1") is False
    assert launcher._is_usable_command(r"D:\nodejs\node.EXE") is True


def test_npm_launcher_script_is_started_with_mcp_subcommand(tmp_path, monkeypatch):
    node = tmp_path / "node.exe"
    node.write_text("", encoding="utf-8")
    bin_dir = tmp_path / "node_modules" / "open-computer-use" / "bin"
    bin_dir.mkdir(parents=True)
    script = bin_dir / "open-computer-use-mcp"
    script.write_text("#!/usr/bin/env node\n", encoding="utf-8")

    def which(name: str):
        if name in {"node", "node.exe"}:
            return str(node)
        if "open-computer-use" in name:
            return str(tmp_path / "open-computer-use-mcp.CMD")
        return None

    monkeypatch.setattr(launcher.shutil, "which", which)
    monkeypatch.delenv("NODE_PATH", raising=False)
    resolved = launcher.resolve_ocu_mcp({})
    assert resolved is not None
    command, args = resolved
    assert command == str(node)
    assert args[-1] == "mcp"
    assert str(script) in args[0]
