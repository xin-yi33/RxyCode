"""Regression: bare imports must resolve to the versioned package objects.

RxyCode ships as the ``RxyCode.RxyCode1_1_0`` package. Several modules use
bare ``from protocol.subagents import ...`` / ``from core import ...`` forms.
``RxyCode.RxyCode1_1_0/__init__.py`` registers a finder plus ``sys.modules``
aliases so both spellings are the same module object.

The subprocess tests keep the repo root OFF ``sys.path`` — the installed-
package layout. In-process tests cover the pytest layout (repo root on path)
where a second copy of ``core.providers`` used to split ``isinstance`` and
monkeypatches after ``test_appserver`` ran in the same worker.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_SUBPROCESS = r"""
import importlib
import os
import sys

# Simulate an installed-package layout: repo root is NOT on sys.path.
# Instead expose the checkout as RxyCode.RxyCode1_1_0 via its parent dir
# (the editable-style top-level namespace) and confirm that importing the
# package registers the bare ``protocol`` alias.
repo = os.environ["RXYCODE_REPO_ROOT"]
repo_parent = os.path.dirname(repo)
sys.path.insert(0, repo_parent)  # makes ``RxyCode`` importable (parent layout)
sys.path.insert(0, os.path.join(repo, "_package_root"))

import RxyCode  # noqa: F401
import RxyCode.RxyCode1_1_0  # noqa: F401  (triggers alias registration)

protocol = sys.modules.get("protocol")
if protocol is None:
    print("RESULT:FAIL no-alias")
    raise SystemExit(1)
paths = list(getattr(protocol, "__path__", []) or [])
if not paths or not str(paths[0]).replace("\\", "/").endswith("/protocol"):
    print("RESULT:FAIL bad-path %r" % (paths,))
    raise SystemExit(1)

mod = importlib.import_module("protocol.subagents")
for symbol in ("AgentDefinition", "TaskRequest", "TaskResult", "ChildStatus"):
    if not hasattr(mod, symbol):
        print("RESULT:FAIL missing %s" % symbol)
        raise SystemExit(1)

from RxyCode.RxyCode1_1_0.tools.subagent_task_tool import subagent_task_tool
if subagent_task_tool.name != "task":
    print("RESULT:FAIL task tool name")
    raise SystemExit(1)

RxyCode.RxyCode1_1_0.unify_bare_package_aliases()
versioned_anthropic = importlib.import_module(
    "RxyCode.RxyCode1_1_0.core.providers.anthropic"
)
RxyCode.RxyCode1_1_0.unify_bare_package_aliases()
bare_anthropic = importlib.import_module("core.providers.anthropic")
if versioned_anthropic.AnthropicProvider is not bare_anthropic.AnthropicProvider:
    print("RESULT:FAIL dual-anthropic")
    raise SystemExit(1)

versioned_tui = importlib.import_module("RxyCode.RxyCode1_1_0.utils.tui")
RxyCode.RxyCode1_1_0.unify_bare_package_aliases()
bare_tui = importlib.import_module("utils.tui")
if versioned_tui.get_tui is not bare_tui.get_tui:
    print("RESULT:FAIL dual-tui")
    raise SystemExit(1)

print("RESULT:OK")
"""


def test_bare_protocol_alias_registered_without_repo_root_on_path() -> None:
    env = dict(os.environ)
    env["RXYCODE_REPO_ROOT"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(Path.home()),
        timeout=120,
    )
    assert "RESULT:OK" in proc.stdout, (
        f"bare protocol alias failed\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )


_WORKER_BIND = r"""
import os
import runpy
import sys
from pathlib import Path

repo = os.environ["RXYCODE_REPO_ROOT"]
os.environ["_RXYCODE_TEST_CHECKOUT"] = repo
for key in (
    "RXYCODE_TEST_ROOT",
    "RXYCODE_TEST_RUN_ID",
    "PYTEST_XDIST_WORKER",
    "PYTEST_CURRENT_TEST",
):
    os.environ.pop(key, None)
sys.path.insert(0, repo)
runpy.run_path(str(Path(repo) / "tests" / "conftest.py"), run_name="rxycode_conftest_bind")
from core import providers
from core.providers.anthropic import AnthropicProvider

ok = isinstance(providers.resolve({"model_name": "claude-opus-5"}), AnthropicProvider)
print("RESULT:OK" if ok else "RESULT:FAIL")
raise SystemExit(0 if ok else 1)
"""


def test_inherited_checkout_env_still_binds_provider_identity() -> None:
    """xdist workers inherit ``_RXYCODE_TEST_CHECKOUT`` from the parent.

    Binding used to skip in that case, so ``from core import providers`` and
    ``from core.providers.anthropic import AnthropicProvider`` were two classes.
    """
    env = dict(os.environ)
    env["RXYCODE_REPO_ROOT"] = str(REPO_ROOT)
    env["_RXYCODE_TEST_CHECKOUT"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", _WORKER_BIND],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(Path.home()),
        timeout=120,
    )
    assert "RESULT:OK" in proc.stdout, (
        "worker-style checkout env split provider identity\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )


def test_bare_and_versioned_provider_classes_are_identical() -> None:
    import importlib

    import RxyCode.RxyCode1_1_0 as pkg

    importlib.import_module("RxyCode.RxyCode1_1_0.core.providers.anthropic")
    importlib.import_module("RxyCode.RxyCode1_1_0.core.providers")
    pkg.unify_bare_package_aliases()

    from core.providers.anthropic import AnthropicProvider as BareAnthropic
    from RxyCode.RxyCode1_1_0.core.providers.anthropic import (
        AnthropicProvider as VersionedAnthropic,
    )
    from core import providers as bare_providers
    from RxyCode.RxyCode1_1_0.core import providers as versioned_providers

    assert BareAnthropic is VersionedAnthropic
    assert bare_providers is versioned_providers
    assert isinstance(
        versioned_providers.resolve({"model_name": "claude-opus-5"}),
        BareAnthropic,
    )


def test_bare_and_versioned_tui_singletons_are_identical() -> None:
    import importlib

    import RxyCode.RxyCode1_1_0 as pkg

    importlib.import_module("RxyCode.RxyCode1_1_0.utils.tui")
    pkg.unify_bare_package_aliases()

    from utils.tui import get_tui as bare_get_tui
    from RxyCode.RxyCode1_1_0.utils.tui import get_tui as versioned_get_tui

    assert bare_get_tui is versioned_get_tui


def test_appserver_import_does_not_split_core_identity() -> None:
    import importlib

    import appserver  # noqa: F401
    import RxyCode.RxyCode1_1_0 as pkg

    importlib.import_module("RxyCode.RxyCode1_1_0.core.providers.anthropic")
    pkg.unify_bare_package_aliases()

    from core.providers.anthropic import AnthropicProvider as BareAnthropic
    from RxyCode.RxyCode1_1_0.core.providers.anthropic import (
        AnthropicProvider as VersionedAnthropic,
    )

    assert BareAnthropic is VersionedAnthropic
    assert appserver.AppServer is not None


def test_protocol_tui_progress_update_is_the_bare_protocol_class() -> None:
    """CI py3.11/3.12 failed when ProtocolTui emitted a second ProgressUpdate."""
    from appserver.tui import ProgressUpdate as TuiProgress
    from appserver.tui import ReasoningSnapshot as TuiSnapshot
    from protocol.notifications import ProgressUpdate, ReasoningSnapshot

    assert TuiProgress is ProgressUpdate
    assert TuiSnapshot is ReasoningSnapshot
