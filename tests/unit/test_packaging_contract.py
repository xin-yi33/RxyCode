from __future__ import annotations

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


def test_pyproject_exposes_the_versioned_console_entrypoint():
    config = _pyproject()
    project = config["project"]

    assert project["name"] == "rxycode"
    assert project["version"] == "1.3.0"
    assert (
        project["scripts"]["rxycode"]
        == "RxyCode.RxyCode1_1_0.entrypoint:main"
    )


def test_setuptools_maps_the_checkout_to_the_versioned_package():
    package_dirs = _pyproject()["tool"]["setuptools"]["package-dir"]

    assert package_dirs[VERSIONED_PACKAGE] == "."
    assert package_dirs["RxyCode"] == "_package_root/RxyCode"


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
    assert "desktop" in jobs
    assert jobs["smoke-install"]["needs"] == "build"
    assert set(jobs["publish"]["needs"]) == {"build", "smoke-install"}
    assert jobs["publish"]["permissions"]["contents"] == "write"
    assert jobs["desktop"]["needs"] == "build"

    build_commands = "\n".join(
        step.get("run", "") for step in jobs["build"]["steps"]
    )
    publish_commands = "\n".join(
        step.get("run", "") for step in jobs["publish"]["steps"]
    )
    release_text = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "macos-latest" not in release_text
    assert "frontend/desktop-app/dist/*.dmg" not in release_text
    assert "frontend/desktop-app/dist/*.zip" in release_text
    assert "frontend/desktop-app/dist/*.exe" in release_text
    assert "frontend/desktop-app/dist/*.AppImage" in release_text
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
    notes_1210 = (PROJECT_ROOT / "docs" / "release-notes" / "RELEASE_NOTES_v1.2.10.md").read_text(
        encoding="utf-8"
    )
    notes_130 = (PROJECT_ROOT / "docs" / "release-notes" / "RELEASE_NOTES_v1.3.0.md").read_text(
        encoding="utf-8"
    )
    gui = (PROJECT_ROOT / "docs" / "GUI.md").read_text(encoding="utf-8")
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "artifactName: RxyCode.Desktop-${version}-win.${ext}" in builder
    assert "artifactName: rxycode-desktop-${version}-setup.${ext}" in builder
    assert "RxyCode.Desktop-1.2.10-win.zip" in notes_1210
    assert "RxyCode.Desktop-1.2.10-arm64-mac.zip" in notes_1210
    assert "rxycode-desktop-1.2.10-win.zip" not in notes_1210
    assert "RxyCode.Desktop-1.3.0-win.zip" in notes_130
    assert "rxycode-desktop-1.3.0-setup.exe" in notes_130
    assert "rxycode-desktop-1.3.0.AppImage" in notes_130
    assert "RxyCode.Desktop-1.3.0-arm64-mac.zip" not in notes_130
    assert "RxyCode.Desktop-<version>-win.zip" in gui
    assert "rxycode-desktop-<version>-win.zip" not in gui
    assert "RxyCode.Desktop-1.3.0-win.zip" in readme


def test_tracked_docs_only_contain_the_github_allowlist():
    import subprocess

    listed = subprocess.check_output(
        ["git", "ls-files", "docs"],
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
        "phase-g",
        "decisions",
        "agents",
        "specs",
    }
    allowed_files = {"quickstart.md", "GUI.md", "DEVELOPMENT-ORDER.md", "development-order.yaml"}
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
        PROJECT_ROOT / "docs" / "release-notes" / "RELEASE_NOTES_v1.3.0.md"
    ).read_text(encoding="utf-8")
    assert "不含 Electron" in notes
    assert "需另下本页 Desktop 资产" in notes
    assert "CLI 包里没有桌面程序" in notes
    fences = re.findall(r"```[^\n]*\n(.*?)```", notes, flags=re.S)
    assert not any(block.strip() == "rxycode gui" for block in fences)
