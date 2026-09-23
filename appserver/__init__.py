"""Stdio JSON-RPC transport for the headless RxyCode core (Phase 2 P4)."""

import importlib
import importlib.util
import sys
import types
from pathlib import Path


def _bind_top_level_checkout_to_canonical_package() -> None:
    """Keep absolute RxyCode imports inside the checkout that launched us.

    Desktop development starts ``python -m appserver``.  This makes
    ``appserver`` a top-level module, while core/tool modules still use the
    canonical ``RxyCode.RxyCode1_1_0`` import path.  A sibling checkout on
    ``sys.path`` could otherwise satisfy that name and mix incompatible code
    versions in one worker process.
    """
    if __name__ != "appserver":
        return
    root = Path(__file__).resolve().parent.parent
    canonical_name = "RxyCode.RxyCode1_1_0"
    existing = sys.modules.get(canonical_name)
    if existing is not None and Path(getattr(existing, "__file__", root)).resolve().parent == root:
        return

    parent = sys.modules.get("RxyCode")
    if parent is None:
        parent = types.ModuleType("RxyCode")
        parent.__path__ = [str(root.parent)]
        sys.modules["RxyCode"] = parent
    package = types.ModuleType(canonical_name)
    package.__file__ = str(root / "__init__.py")
    package.__path__ = [str(root)]
    sys.modules[canonical_name] = package
    init_file = root / "__init__.py"
    if init_file.exists():
        source = init_file.read_text(encoding="utf-8-sig")
        exec(compile(source, str(init_file), "exec"), package.__dict__)  # noqa: S102
    parent.RxyCode1_1_0 = package


class _BarePackageAliasLoader:
    """Load a bare name by returning the already-executed canonical module."""

    def __init__(self, canonical_name: str) -> None:
        self.canonical_name = canonical_name

    def create_module(self, spec):  # noqa: ANN001 - importlib loader protocol
        return importlib.import_module(self.canonical_name)

    def exec_module(self, module) -> None:  # noqa: ANN001, ARG002
        return None


class _BarePackageRedirectFinder:
    """sys.meta_path hook: bare ``pkg.X`` is ``RxyCode.RxyCode1_1_0.pkg.X``.

    The root-package unify/finder can still leave two module objects with the
    same ``__name__`` / ``__file__``.  Redirecting the spec keeps one object.
    """

    def find_spec(self, fullname, path, target=None):  # noqa: ANN001, ARG002
        root = fullname.partition(".")[0]
        if root not in _UNIFIED_TOP_LEVEL_PACKAGES:
            return None
        canonical = "RxyCode.RxyCode1_1_0." + fullname
        existing = sys.modules.get(canonical)
        if existing is not None:
            is_package = hasattr(existing, "__path__")
            origin = getattr(existing, "__file__", None)
        else:
            try:
                can_spec = importlib.util.find_spec(canonical)
            except (ImportError, ModuleNotFoundError, ValueError):
                return None
            if can_spec is None:
                return None
            is_package = can_spec.submodule_search_locations is not None
            origin = can_spec.origin
        return importlib.util.spec_from_loader(
            fullname,
            _BarePackageAliasLoader(canonical),
            origin=origin,
            is_package=is_package,
        )


def _register_bare_core_alias() -> None:
    """Point bare package names at this checkout's canonical modules.

    Install the redirect finder first (``is`` identity), then run the root
    package ``unify_bare_package_aliases`` so already-imported names match.
    """
    if not any(type(finder) is _BarePackageRedirectFinder for finder in sys.meta_path):
        sys.meta_path.insert(0, _BarePackageRedirectFinder())
    pkg = sys.modules.get("RxyCode.RxyCode1_1_0")
    unify = getattr(pkg, "unify_bare_package_aliases", None)
    if callable(unify):
        unify()
    for name in list(sys.modules):
        root = name.partition(".")[0]
        if root not in _UNIFIED_TOP_LEVEL_PACKAGES:
            continue
        try:
            canonical = importlib.import_module("RxyCode.RxyCode1_1_0." + name)
        except ImportError:
            continue
        sys.modules[name] = canonical
    if "core" not in sys.modules:
        try:
            sys.modules["core"] = importlib.import_module("RxyCode.RxyCode1_1_0.core")
        except ImportError:
            return


_bind_top_level_checkout_to_canonical_package()

# Same source as ``RxyCode.RxyCode1_1_0._BARE_PACKAGES``.  ``appserver`` is
# intentionally allowed two objects (``python -m appserver`` vs canonical).
_root_pkg = sys.modules.get("RxyCode.RxyCode1_1_0")
_UNIFIED_TOP_LEVEL_PACKAGES = frozenset(
    name
    for name in getattr(
        _root_pkg,
        "_BARE_PACKAGES",
        frozenset({"config", "core", "execution", "memory", "protocol", "tools"}),
    )
    if name != "appserver"
)

_register_bare_core_alias()

from .server import AppServer

_register_bare_core_alias()

__all__ = ["AppServer"]
