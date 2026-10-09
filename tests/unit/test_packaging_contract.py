from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERSIONED_PACKAGE = "RxyCode.RxyCode1_1_0"


def _pyproject() -> dict:
    return tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )


def _workflow(name: str) -> dict:
    return yaml.load(
        (PROJECT_ROOT / ".github" / "workflows" / name).read_text(
            encoding="utf-8"
        ),
        Loader=yaml.BaseLoader,
    )


def test_installer_ships_playwright_package_not_the_browser_binary():
    req = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "playwright>=" in req
    script = (
        PROJECT_ROOT / "frontend" / "desktop-app" / "scripts" / "prepare-runtime.mts"
    ).read_text(encoding="utf-8")
    live_install = [
        line
        for line in script.splitlines()
        if "playwright install" in line and not line.lstrip().startswith("//")
    ]
    assert live_install == []
    browser = (PROJECT_ROOT / "tools" / "virtual_browser.py").read_text(encoding="utf-8")
    launch = browser.split("def _launch_browser", 1)[1].split("def _ensure_page", 1)[0]
    assert "chromium.launch(headless=True)" in launch
    assert "channel=" not in launch
    assert "_install_bundled_chromium" in launch


def test_pyproject_exposes_the_versioned_console_entrypoint():
    config = _pyproject()
    project = config["project"]

    assert project["name"] == "rxycode"
    assert project["version"] == "1.4.2"
    assert (
        project["scripts"]["rxycode"]
        == "RxyCode.RxyCode1_1_0.entrypoint:main"
    )


def test_setuptools_maps_the_checkout_to_the_versioned_package():
    package_dirs = _pyproject()["tool"]["setuptools"]["package-dir"]

    assert package_dirs[VERSIONED_PACKAGE] == "."
    assert package_dirs["RxyCode"] == "_package_root/RxyCode"


def test_product_version_is_consistent_without_bumping_wire_protocol():
    from appserver.release import schema_digest
    from protocol.version import APPSERVER_VERSION, PROTOCOL_VERSION

    version = _pyproject()["project"]["version"]
    assert APPSERVER_VERSION == version
    assert PROTOCOL_VERSION == "1.1.0"
    source = (PROJECT_ROOT / "__init__.py").read_text(encoding="utf-8-sig")
    assert re.search(r'__version__ = "([^"]+)"', source).group(1) == version
    for package in ("frontend", "frontend/opentui-app", "frontend/desktop-app"):
        package_dir = PROJECT_ROOT / package
        metadata = json.loads((package_dir / "package.json").read_text(encoding="utf-8-sig"))
        assert metadata["version"] == version, package
        lock_path = package_dir / "package-lock.json"
        if lock_path.exists():
            lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
            assert lock["version"] == lock["packages"][""]["version"] == version
    for platform in ("windows", "linux", "macos"):
        manifest = json.loads(
            (PROJECT_ROOT / "packaging/runtimes" / f"{platform}.json").read_text(
                encoding="utf-8-sig"
            )
        )
        assert manifest["appserver_version"] == version
        assert manifest["protocol_version"] == PROTOCOL_VERSION
        assert manifest["schema_digest"] == schema_digest()
    sources = {
        "install.ps1": f'$DefaultVersion = "{version}"',
        "install.sh": f'DEFAULT_VERSION="{version}"',
        "mcp/client.py": f'"clientInfo": {{"name": "RxyCode", "version": "{version}"}}',
        "frontend/opentui-app/src/format.ts": f'APP_VERSION = "{version}"',
        "frontend/opentui-app/src/transport/stdioTransport.ts": f'client_version: "{version}"',
        "frontend/src/App.tsx": f'RxyCode v{version}',
        "frontend/src/opentui/format.ts": f'RxyCode v{version}',
    }
    for path, expected in sources.items():
        assert expected in (PROJECT_ROOT / path).read_text(encoding="utf-8-sig"), path


def test_pytest_rebinds_checkout_after_stale_editable_package_is_preloaded(tmp_path):
    """A stale editable finder must not leak its old version into this checkout.

    The subprocess deliberately preloads a small 1.4.1 package through the
    same class-shaped finder emitted by setuptools.  The target conftest must
    remove that finder and purge its already-imported canonical children
    before the 1.4.2 packaging contract imports ``protocol.version``.
    """
    stale_root = tmp_path / "stale"
    stale_package = stale_root / "RxyCode" / "RxyCode1_1_0"
    (stale_package / "protocol").mkdir(parents=True)
    (stale_root / "RxyCode" / "__init__.py").write_text(
        "__path__ = []\n", encoding="utf-8"
    )
    (stale_package / "__init__.py").write_text(
        "__path__ = [r'" + str(stale_package).replace("\\", "\\\\") + "']\n",
        encoding="utf-8",
    )
    (stale_package / "protocol" / "__init__.py").write_text(
        "\n", encoding="utf-8"
    )
    (stale_package / "protocol" / "version.py").write_text(
        'APPSERVER_VERSION = "1.4.1"\nPROTOCOL_VERSION = "1.1.0"\n',
        encoding="utf-8",
    )

    script = f"""
import importlib.abc
import importlib.util
import sys
from pathlib import Path

stale = Path({str(stale_root)!r})

class _EditableFinder(importlib.abc.MetaPathFinder):
    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        mapping = {{
            "RxyCode": stale / "RxyCode" / "__init__.py",
            "RxyCode.RxyCode1_1_0": stale / "RxyCode" / "RxyCode1_1_0" / "__init__.py",
        }}
        filename = mapping.get(fullname)
        if filename is None:
            return None
        return importlib.util.spec_from_file_location(
            fullname,
            filename,
            submodule_search_locations=[str(filename.parent)],
        )

_EditableFinder.__module__ = "__editable___stale_finder"
sys.meta_path.insert(0, _EditableFinder)
from RxyCode.RxyCode1_1_0.protocol.version import APPSERVER_VERSION
assert APPSERVER_VERSION == "1.4.1"
import pytest
raise SystemExit(pytest.main([
    "tests/unit/test_packaging_contract.py",
    "-k",
    "test_product_version_is_consistent_without_bumping_wire_protocol",
    "-q",
    "-p",
    "no:cacheprovider",
], plugins=[]))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    # The child pytest is a fresh lane, not an xdist worker of the parent.
    # Give it an exclusive root/run id so conftest's fail-closed mkdir remains
    # meaningful even when this test itself runs under xdist.
    env["RXYCODE_TEST_ROOT"] = str(tmp_path / "child-test-root")
    env["RXYCODE_TEST_RUN_ID"] = f"packaging-child-{os.getpid()}-{tmp_path.name}"
    for key in (
        "PYTEST_XDIST_WORKER",
        "PYTEST_XDIST_WORKER_COUNT",
        "PYTEST_XDIST_TESTRUNUID",
        "PYTEST_CURRENT_TEST",
    ):
        env.pop(key, None)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_console_and_module_launcher_sources_are_present():
    expected_sources = (
        PROJECT_ROOT / "entrypoint.py",
        PROJECT_ROOT / "__main__.py",
        PROJECT_ROOT / "MANIFEST.in",
        PROJECT_ROOT / "install.ps1",
        PROJECT_ROOT / "install.sh",
        PROJECT_ROOT / "frontend" / "dist" / "index.js",
        PROJECT_ROOT / "frontend" / "package.json",
        PROJECT_ROOT / "_package_root" / "RxyCode" / "__init__.py",
        PROJECT_ROOT / "_package_root" / "RxyCode" / "main.py",
        PROJECT_ROOT / "_package_root" / "RxyCode" / "__main__.py",
    )

    missing = [
        str(path.relative_to(PROJECT_ROOT))
        for path in expected_sources
        if not path.is_file()
    ]
    assert not missing, f"missing package entrypoint sources: {missing}"


def test_manifest_includes_opentui_and_ink_runtimes_and_excludes_node_modules():
    manifest = (PROJECT_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "recursive-include frontend/dist *.js" in manifest
    assert "include frontend/package.json" in manifest
    assert "recursive-include frontend/opentui-app/src *" in manifest
    assert "include frontend/opentui-app/package.json" in manifest
    assert "recursive-include frontend/protocol-client/src *" in manifest
    assert "include frontend/protocol-client/package.json" in manifest
    assert "include core/agents/teams/*.yaml" in manifest
    assert "prune frontend/node_modules" in manifest
    assert "prune frontend/opentui-app/node_modules" in manifest
    assert "prune frontend/protocol-client/node_modules" in manifest
    assert "prune evals" in manifest
    assert "prune tests" in manifest
    assert "prune scripts" in manifest
    assert "exclude AGENTS.md" in manifest
    assert "global-exclude .coveragerc" in manifest
    assert "recursive-include evals" not in manifest


def test_pyproject_does_not_ship_evals_or_repo_harness_files():
    packages = set(_pyproject()["tool"]["setuptools"]["packages"])
    assert "RxyCode.RxyCode1_1_0.evals" not in packages
    excluded = "\n".join(
        _pyproject()["tool"]["setuptools"]["exclude-package-data"][VERSIONED_PACKAGE]
    )
    assert "evals/**" in excluded
    assert "scripts/**" in excluded
    assert "AGENTS.md" in excluded
    assert ".coveragerc" in excluded


def test_package_data_ships_opentui_sources():
    package_data = _pyproject()["tool"]["setuptools"]["package-data"][
        VERSIONED_PACKAGE
    ]
    joined = "\n".join(package_data)
    assert "frontend/dist/*.js" in joined
    assert "frontend/opentui-app/package.json" in joined
    assert "frontend/opentui-app/src/**/*" in joined
    assert "frontend/protocol-client/package.json" in joined
    assert "frontend/protocol-client/src/**/*" in joined
    assert "core/agents/teams/*.yaml" in joined


def test_pyproject_includes_every_core_subpackage():
    packages = set(_pyproject()["tool"]["setuptools"]["packages"])
    missing = []
    for init in (PROJECT_ROOT / "core").rglob("__init__.py"):
        rel = init.parent.relative_to(PROJECT_ROOT)
        dotted = "RxyCode.RxyCode1_1_0." + ".".join(rel.parts)
        if dotted not in packages:
            missing.append(dotted)
    assert not missing, f"pyproject omits core subpackages: {missing}"


def test_pyproject_ships_the_sandbox_subpackage():
    """2026-10-07 审计回归：core.sandbox 漏进包清单时，installed 包连
    os_sandbox disabled 都会在 utils/shell.py 导入点 ModuleNotFoundError。"""
    packages = set(_pyproject()["tool"]["setuptools"]["packages"])
    assert "RxyCode.RxyCode1_1_0.core.sandbox" in packages


def test_nsis_custom_init_honors_silent_install_dir():
    nsh = (PROJECT_ROOT / "frontend" / "desktop-app" / "build" / "installer.nsh").read_text(
        encoding="utf-8"
    )
    assert "!macro customInit" in nsh
    assert "rxy_use_default" in nsh
    assert 'StrCmp "$INSTDIR" "" rxy_use_default' in nsh
    assert nsh.count("StrCpy $INSTDIR") == 1


def test_ci_smokes_the_installed_package_without_namespace_links():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "python -m pip install -e . --no-deps" in workflow
    assert "rxycode\" --version" in workflow or "rxycode --version" in workflow
    assert "-m RxyCode --version" in workflow
    assert "New-Item -ItemType Junction" not in workflow
    assert "ln -s" not in workflow


def test_api_server_init_does_not_chdir_into_the_installed_package():
    source = (PROJECT_ROOT / "api_server.py").read_text(encoding="utf-8")
    assert "os.chdir(_project_root)" not in source
    assert "Keep the caller's cwd" in source


def test_release_waits_for_cross_platform_installed_smoke_tests():
    workflow = _workflow("release.yml")

    assert workflow["on"]["push"]["tags"] == ["v*"]
    assert workflow["permissions"]["contents"] == "read"

    jobs = workflow["jobs"]
    assert "desktop" not in jobs
    assert jobs["smoke-install"]["needs"] == "build"
    assert set(jobs["publish"]["needs"]) == {"build", "smoke-install"}
    assert jobs["publish"]["permissions"]["contents"] == "write"

    build_commands = "\n".join(
        step.get("run", "") for step in jobs["build"]["steps"]
    )
    publish_commands = "\n".join(
        step.get("run", "") for step in jobs["publish"]["steps"]
    )
    release_text = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "frontend/desktop-app/dist/*.dmg" not in release_text
    assert "frontend/desktop-app/dist/*.zip" not in release_text
    assert "python -m build --sdist" in build_commands
    assert "--no-isolation" in build_commands
    assert "python -m twine check dist/*" in build_commands
    assert "dist/*.tar.gz" in publish_commands
    assert "*.whl" in publish_commands
    assert "gh release create" in publish_commands
    assert "--verify-tag" in publish_commands


def test_published_desktop_asset_names_match_electron_builder():
    builder = (PROJECT_ROOT / "frontend" / "desktop-app" / "electron-builder.yml").read_text(
        encoding="utf-8"
    )
    notes = (PROJECT_ROOT / "docs" / "release-notes" / "RELEASE_NOTES_v1.2.10.md").read_text(
        encoding="utf-8"
    )
    gui = (PROJECT_ROOT / "docs" / "GUI.md").read_text(encoding="utf-8")
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "artifactName: RxyCode.Desktop-${version}-win.${ext}" in builder
    assert "artifactName: rxycode-desktop-${version}-setup.${ext}" in builder
    assert "RxyCode.Desktop-1.2.10-win.zip" in notes
    assert "RxyCode.Desktop-1.2.10-arm64-mac.zip" in notes
    assert "rxycode-desktop-1.2.10-win.zip" not in notes
    assert "RxyCode.Desktop-<version>-win.zip" in gui
    assert "rxycode-desktop-<version>-win.zip" not in gui
    assert "RxyCode.Desktop-1.2.10-win.zip" in readme


def test_tracked_docs_only_contain_the_github_allowlist():
    import subprocess

    listed = subprocess.check_output(
        ["git", "-c", "core.quotepath=false", "ls-files", "docs"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    allowed_dirs = {
        "agent",
        "assets",
        "imgs",
        "modules",
        "release-notes",
        # feat/phase-g-backend unique construction docs kept alongside master
        # GitHub allowlist.
        "phase-g",
        "decisions",
        "agents",
        "specs",
    }
    allowed_files = {
        "quickstart.md",
        "GUI.md",
        "DEVELOPMENT-ORDER.md",
        "development-order.yaml",
    }
    unexpected = []
    for line in listed.splitlines():
        rel = line[5:] if line.startswith("docs/") else line
        if not rel:
            continue
        first = rel.split("/", 1)[0]
        if "/" in rel:
            if first not in allowed_dirs:
                unexpected.append(line)
        elif first not in allowed_files:
            unexpected.append(line)
    assert not unexpected, f"tracked docs outside GitHub allowlist: {unexpected}"


def test_release_notes_separate_cli_install_from_desktop_gui():
    import re

    notes = (
        PROJECT_ROOT / "docs" / "release-notes" / "RELEASE_NOTES_v1.2.10.md"
    ).read_text(encoding="utf-8")
    assert "不含 Electron" in notes
    assert "需另下本页 Desktop 资产" in notes
    assert "CLI 包里没有桌面程序" in notes
    fences = re.findall(r"```[^\n]*\n(.*?)```", notes, flags=re.S)
    assert not any(block.strip() == "rxycode gui" for block in fences)
