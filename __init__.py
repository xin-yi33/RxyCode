"""RxyCode 1.2.11 - LangGraph-based agent."""

from __future__ import annotations

import builtins as _builtins
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys as _sys
import types as _types

__version__ = "1.2.11"

__all__ = ["__version__", "unify_bare_package_aliases", "install_test_import_unify_hook"]

_CANONICAL_PREFIX = "RxyCode.RxyCode1_1_0"
_CHECKOUT_ROOT = __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0]
_BARE_PACKAGES = frozenset(
    {
        "appserver",
        "cache",
        "config",
        "core",
        "evals",
        "execution",
        "history",
        "log",
        "lsp",
        "mcp",
        "memory",
        "planning",
        "protocol",
        "rag",
        "recovery",
        "scheduler",
        "synthesis",
        "tools",
        "utils",
        "validation",
    }
)
_BARE_MODULES = frozenset({"api_server"})


def _is_bare_name(name: str) -> bool:
    if name in _BARE_MODULES:
        return True
    return name.split(".", 1)[0] in _BARE_PACKAGES


_mirrored_canonical: dict[str, int] = {}


def _is_checkout_module(module: _types.ModuleType | None) -> bool:
    if module is None:
        return False
    path = getattr(module, "__file__", None)
    if not path:
        return False
    normalized = path.replace("\\", "/")
    root = _CHECKOUT_ROOT.replace("\\", "/")
    return normalized == root or normalized.startswith(f"{root}/")


def _same_source(left: _types.ModuleType | None, right: _types.ModuleType | None) -> bool:
    if left is None or right is None:
        return False
    if left is right:
        return True
    left_file = getattr(left, "__file__", None)
    right_file = getattr(right, "__file__", None)
    return bool(left_file) and left_file == right_file


def _apply_bare_alias(key: str, short: str, module: _types.ModuleType) -> None:
    parent_name, _, child = short.rpartition(".")
    parent = _sys.modules.get(parent_name)
    canon_parent_name, _, canon_child = key.rpartition(".")
    canon_parent = _sys.modules.get(canon_parent_name)
    # Keep the submodule object already bound on a package.  ``core.providers``
    # instantiates provider classes at import; replacing that module later
    # splits ``isinstance`` against the leftover ``_PROVIDERS`` instances.
    for owner, attr in ((parent, child), (canon_parent, canon_child)):
        if owner is None or not attr:
            continue
        bound = getattr(owner, attr, None)
        if isinstance(bound, _types.ModuleType) and _same_source(bound, module):
            module = bound
            break
    else:
        current_canon = _sys.modules.get(key)
        current_short = _sys.modules.get(short)
        if current_canon is not None and _same_source(current_canon, module):
            module = current_canon
        elif current_short is not None and _same_source(current_short, module):
            module = current_short
    if short == "appserver" or short.startswith("appserver."):
        _sys.modules.setdefault(short, module)
        if parent is not None and child and not hasattr(parent, child):
            setattr(parent, child, module)
    else:
        _sys.modules[short] = module
        if parent is not None and child:
            setattr(parent, child, module)
    _sys.modules[key] = module
    canon_parent_name, _, canon_child = key.rpartition(".")
    canon_parent = _sys.modules.get(canon_parent_name)
    if canon_parent is not None and canon_child:
        setattr(canon_parent, canon_child, module)
    _remap_descendant_aliases(key, short, module)
    _mirrored_canonical[key] = id(module)


def _remap_descendant_aliases(key: str, short: str, module: _types.ModuleType) -> None:
    """Point leftover ``core.foo.bar`` keys at the winner package's children.

    PathFinder can exec ``core.providers.anthropic`` before the versioned
    package is imported.  After ``core.providers`` is unified, that stale
    child key would still supply a second ``AnthropicProvider`` class.

    Walk ``__dict__`` only: ``getattr`` on ``execution`` would lazy-import
    ``Executor`` and pull the Graph stack into Desktop's fast path.
    """
    if not hasattr(module, "__path__"):
        return
    short_prefix = f"{short}."
    key_prefix = f"{key}."
    for name, child in list(_sys.modules.items()):
        if name.startswith(short_prefix):
            rest = name[len(short_prefix) :]
        elif name.startswith(key_prefix):
            rest = name[len(key_prefix) :]
        else:
            continue
        if not rest:
            continue
        winner = module
        for part in rest.split("."):
            nxt = winner.__dict__.get(part)
            if not isinstance(nxt, _types.ModuleType):
                winner = _sys.modules.get(f"{key}.{rest}") or _sys.modules.get(
                    f"{short}.{rest}"
                )
                break
            winner = nxt
        if winner is None:
            continue
        if child is not None and child is not winner and not _same_source(child, winner):
            continue
        _sys.modules[f"{short}.{rest}"] = winner
        _sys.modules[f"{key}.{rest}"] = winner


def _mirror_canonical_module(key: str, module: _types.ModuleType) -> None:
    prefix = f"{_CANONICAL_PREFIX}."
    if not key.startswith(prefix):
        return
    short = key[len(prefix) :]
    if not _is_bare_name(short):
        return
    _apply_bare_alias(key, short, module)


def unify_bare_package_aliases(*, force: bool = False) -> None:
    """Point bare names at already-imported versioned modules.

    ``from core import providers`` uses the ``core.providers`` attribute when
    ``sys.modules["core"]`` is the versioned package, but
    ``from core.providers.anthropic import …`` looks up the bare key
    ``core.providers``.  Those must be the same object so ``isinstance``,
    monkeypatches, and process singletons apply.

    ``appserver`` is only filled when missing: ``python -m appserver`` and
    tests that patch ``appserver.server`` need the top-level package loader.

    Newly seen canonical modules are mirrored, and previously mirrored short
    names are repaired when they drift to a second copy of the same file.
    Production ``python -m appserver`` does not wrap ``__import__``; the
    finder calls ``_mirror_canonical_module`` in O(1).
    """
    prefix = f"{_CANONICAL_PREFIX}."
    if force:
        _mirrored_canonical.clear()
    else:
        for key, mirrored_id in list(_mirrored_canonical.items()):
            module = _sys.modules.get(key)
            if module is None:
                _mirrored_canonical.pop(key, None)
                continue
            short = key[len(prefix) :]
            parent_name, _, child = short.rpartition(".")
            parent = _sys.modules.get(parent_name) if child else None
            short_ok = _sys.modules.get(short) is module
            parent_ok = (not child) or (
                parent is not None and getattr(parent, child, None) is module
            )
            canon_parent_name, _, canon_child = key.rpartition(".")
            canon_parent = _sys.modules.get(canon_parent_name)
            canon_parent_ok = (not canon_child) or (
                canon_parent is not None and getattr(canon_parent, canon_child, None) is module
            )
            keys_ok = _sys.modules.get(key) is module
            if short_ok and parent_ok and canon_parent_ok and keys_ok and id(module) == mirrored_id:
                continue
            _apply_bare_alias(key, short, module)
    new_items: list[tuple[str, str, _types.ModuleType]] = []
    for key, module in list(_sys.modules.items()):
        if key in _mirrored_canonical or not key.startswith(prefix):
            continue
        short = key[len(prefix) :]
        if not _is_bare_name(short):
            continue
        new_items.append((key, short, module))
    new_items.sort(key=lambda item: item[0].count("."))
    for key, short, module in new_items:
        _apply_bare_alias(key, short, module)


class _ReuseLoader(importlib.abc.Loader):
    """Reuse a canonical module object for a bare import name."""

    def __init__(self, module: _types.ModuleType) -> None:
        self._module = module

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> _types.ModuleType:
        return self._module

    def exec_module(self, module: _types.ModuleType) -> None:
        return

    def get_code(self, fullname: str):
        spec = getattr(self._module, "__spec__", None)
        loader = getattr(spec, "loader", None) if spec is not None else None
        get_code = getattr(loader, "get_code", None)
        if get_code is None:
            return None
        return get_code(getattr(self._module, "__name__", fullname))


class _BareChildAliasFinder(importlib.abc.MetaPathFinder):
    """When ``core`` already *is* the versioned package, load ``core.foo`` from it.

    Does not intercept ``appserver`` or ``__main__`` so ``python -m appserver``
    and ``sys.modules['core.agent_v2'] = Fake`` keep working.
    """

    _mark = "_rxycode_bare_child_alias"

    def find_spec(self, fullname, path, target=None):  # noqa: ANN001
        if fullname.startswith("RxyCode") or not _is_bare_name(fullname):
            return None
        if fullname == "appserver" or fullname.startswith("appserver."):
            return None
        if fullname.rsplit(".", 1)[-1] == "__main__":
            return None
        canonical_name = f"{_CANONICAL_PREFIX}.{fullname}"
        existing = _sys.modules.get(canonical_name) or _sys.modules.get(fullname)
        if existing is not None:
            _sys.modules.setdefault(canonical_name, existing)
            _mirror_canonical_module(canonical_name, existing)
            spec = importlib.util.spec_from_loader(
                fullname,
                _ReuseLoader(existing),
                origin=getattr(existing, "__file__", None),
                is_package=hasattr(existing, "__path__"),
            )
            if spec is not None and hasattr(existing, "__path__"):
                spec.submodule_search_locations = list(existing.__path__)
            return spec
        parent_name, sep, _child = fullname.rpartition(".")
        if sep:
            parent = _sys.modules.get(parent_name)
            if parent is not None:
                parent_mod_name = getattr(parent, "__name__", "") or ""
                if not (
                    parent_mod_name == _CANONICAL_PREFIX
                    or parent_mod_name.startswith(f"{_CANONICAL_PREFIX}.")
                    or _is_checkout_module(parent)
                ):
                    return None
        try:
            module = importlib.import_module(canonical_name)
        except ImportError:
            return None
        _mirror_canonical_module(canonical_name, module)
        spec = importlib.util.spec_from_loader(
            fullname,
            _ReuseLoader(module),
            origin=getattr(module, "__file__", None),
            is_package=hasattr(module, "__path__"),
        )
        if spec is not None and hasattr(module, "__path__"):
            spec.submodule_search_locations = list(module.__path__)
        return spec


def _install_bare_child_finder() -> None:
    if any(
        getattr(finder, "_mark", None) == _BareChildAliasFinder._mark
        for finder in _sys.meta_path
    ):
        return
    _sys.meta_path.insert(0, _BareChildAliasFinder())


def install_test_import_unify_hook() -> None:
    """Full remirror after canonical imports.  Tests only."""
    current = _builtins.__import__
    if getattr(current, "_rxycode_bare_alias_mirror", False):
        return

    def _import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        module = current(name, globals, locals, fromlist, level)
        imported = name if isinstance(name, str) else ""
        mod_name = getattr(module, "__name__", "") or ""
        if (
            mod_name == _CANONICAL_PREFIX
            or mod_name.startswith(f"{_CANONICAL_PREFIX}.")
            or imported == _CANONICAL_PREFIX
            or imported.startswith(f"{_CANONICAL_PREFIX}.")
            or (imported and _is_bare_name(imported))
        ):
            unify_bare_package_aliases()
        return module

    _import._rxycode_bare_alias_mirror = True  # type: ignore[attr-defined]
    _builtins.__import__ = _import


def _register_bare_protocol_alias() -> None:
    """Make ``import protocol`` resolve to this package's protocol subpackage.

    Several modules (``core/subagents/*``, ``tools/subagent_task_tool.py``,
    ``appserver/*``) use the bare ``from protocol.subagents import ...`` form.
    Under a source checkout that works because the repo root is on ``sys.path``;
    under an installed/editable package the protocol package lives at
    ``RxyCode.RxyCode1_1_0.protocol`` and the bare name is missing.  Registering
    the alias here means ``rxycode`` works from any working directory.
    """
    _install_bare_child_finder()
    try:
        protocol = importlib.import_module(f"{_CANONICAL_PREFIX}.protocol")
    except ImportError:
        unify_bare_package_aliases()
        return
    _sys.modules["protocol"] = protocol
    unify_bare_package_aliases()


_register_bare_protocol_alias()
