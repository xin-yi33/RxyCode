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
    assert project["version"] == "1.2.0"
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


def test_manifest_includes_the_ink_runtime_and_excludes_node_modules():
    manifest = (PROJECT_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "recursive-include frontend/dist *.js" in manifest
    assert "include frontend/package.json" in manifest
    assert "prune frontend/node_modules" in manifest


def test_ci_smokes_the_installed_package_without_namespace_links():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "python -m pip install -e . --no-deps" in workflow
    assert "rxycode\" --version" in workflow or "rxycode --version" in workflow
    assert "-m RxyCode --version" in workflow
    assert "New-Item -ItemType Junction" not in workflow
    assert "ln -s" not in workflow


def test_release_waits_for_cross_platform_installed_smoke_tests():
    workflow = _workflow("release.yml")

    assert workflow["on"]["push"]["tags"] == ["v*"]
    assert workflow["permissions"]["contents"] == "read"

    jobs = workflow["jobs"]
    assert jobs["smoke-install"]["needs"] == "build"
    assert set(jobs["publish"]["needs"]) == {"build", "smoke-install"}
    assert jobs["publish"]["permissions"]["contents"] == "write"

    build_commands = "\n".join(
        step.get("run", "") for step in jobs["build"]["steps"]
    )
    publish_commands = "\n".join(
        step.get("run", "") for step in jobs["publish"]["steps"]
    )
    assert "python -m build --no-isolation" in build_commands
    assert "python -m twine check dist/*" in build_commands
    assert "gh release create" in publish_commands
    assert "--verify-tag" in publish_commands
