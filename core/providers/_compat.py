"""Compatibility imports for source-tree and installed-package layouts.

The project is exercised both as ``core.*`` from the repository root and as
``RxyCode.RxyCode1_1_0.*`` from the built package.  Keeping these lookups in a
single top-level helper avoids repeating function-scoped try/except imports in
every provider and preserves the P7 lazy-import budget.
"""

from __future__ import annotations

from importlib import import_module


def _load(module_suffix: str):
    last_error: ImportError | None = None
    # Source-tree imports must win over an unrelated globally installed
    # RxyCode package; installed-package imports must stay fully qualified.
    # Choose the order from this module's own package rather than probing a
    # potentially stale package first.
    package_name = __package__ or ""
    prefixes = (
        ("RxyCode.RxyCode1_1_0.", "")
        if package_name.startswith("RxyCode.RxyCode1_1_0")
        else ("", "RxyCode.RxyCode1_1_0.")
    )
    for prefix in prefixes:
        try:
            return import_module(prefix + module_suffix)
        except ModuleNotFoundError as exc:
            # Only a missing candidate module is a layout miss.  Dependency
            # failures inside an existing module must remain visible.
            if exc.name != prefix + module_suffix:
                raise
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ImportError(module_suffix)


_capabilities = _load("config.model_capabilities")
_catalog = _load("core.catalog")
_transport = _load("config.model_transport")
_endpoint = _load("config.model_endpoint")

DEFAULT_CAPABILITIES = _capabilities.DEFAULT_CAPABILITIES
ModelCapabilities = _capabilities.ModelCapabilities
ModelPricing = _capabilities.ModelPricing
UsageFieldMap = _capabilities.UsageFieldMap
canonical_model_id = _catalog.canonical_model_id

ANTHROPIC_MESSAGES_TRANSPORT = _transport.ANTHROPIC_MESSAGES_TRANSPORT
LLMTransport = _transport.LLMTransport
OPENAI_CHAT_TRANSPORT = _transport.OPENAI_CHAT_TRANSPORT
OPENAI_RESPONSES_TRANSPORT = _transport.OPENAI_RESPONSES_TRANSPORT
normalize_api_transport = _transport.normalize_api_transport
normalize_transport_candidates = _transport.normalize_transport_candidates

llm_client_base_url = _endpoint.llm_client_base_url
normalize_llm_endpoint = _endpoint.normalize_llm_endpoint
normalize_resource_path = _endpoint.normalize_resource_path
infer_transport_from_resource_path = _endpoint.infer_transport_from_resource_path
rewrite_sdk_request_url = _endpoint.rewrite_sdk_request_url
resource_path_request_hook = _endpoint.resource_path_request_hook
ensure_resource_path_rewritable = _endpoint.ensure_resource_path_rewritable
