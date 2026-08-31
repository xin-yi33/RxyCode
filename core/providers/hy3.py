"""Tencent HY3 provider policy for OpenCode Go and compatible gateways.

The formal ``hy3`` model is intentionally separate from preview/future IDs.
OpenCode Go currently documents HY3 on Chat Completions, so this provider adds
capability identity and a stable transport decision without copying Tencent
TokenHub-only request extensions into the gateway wire contract.

Sources (checked 2026-08-25):
  - https://cloud.tencent.com/document/product/1823/130051
  - https://opencode.ai/docs/go/
"""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlsplit

from ._compat import DEFAULT_CAPABILITIES, ModelCapabilities, ModelPricing

from .base import BaseProvider, CHAT_TRANSPORT


_HY3_PRICING = ModelPricing(
    as_of="2026-08-25",
    source_url="https://cloud.tencent.com/document/product/1823/130051",
)


def _host(base_url: str) -> str:
    try:
        return (urlsplit(base_url).hostname or "").casefold()
    except ValueError:
        return ""


class Hy3Provider(BaseProvider):
    """Provider for the formal HY3 ID; preview aliases are out of scope."""

    name = "hy3"

    def matches(self, base_url: str, model_name: str) -> bool:
        del base_url
        return str(model_name or "").strip().casefold() == "hy3"

    def transport_candidates(self, model_config: dict) -> tuple[str, ...]:
        # The OpenCode Go contract currently exposes HY3 through
        # /chat/completions.  Do not probe undocumented Responses semantics.
        pinned = self._resource_path_candidates(model_config)
        if pinned is not None:
            if pinned != (CHAT_TRANSPORT,):
                raise ValueError("HY3 only supports api_transport=openai_chat")
            return pinned
        explicit = self.explicit_transport_candidates(model_config)
        if explicit is not None and explicit != (CHAT_TRANSPORT,):
            raise ValueError("HY3 only supports api_transport=openai_chat")
        return (CHAT_TRANSPORT,)

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        # Model-level limits come from Tencent's formal HY3 model table.  They
        # describe safe clamps, not permission to forward TokenHub-only fields
        # through a third-party gateway.
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            context_window=256_000,
            compaction_threshold=230_400,
            max_output_tokens=128_000,
            supports_reasoning=True,
            thinking_default_on=False,
            supports_function_calling=True,
            structured_output="function_calling",
            pricing=_HY3_PRICING,
        )
        return caps.merged_with_overrides(model_config)

    def llm_kwargs(self, model_config: dict, caps: ModelCapabilities) -> dict:
        kwargs = super().llm_kwargs(model_config, caps)
        if _host(str(model_config.get("base_url") or "")) == "opencode.ai":
            kwargs.pop("reasoning_effort", None)
            body = dict(kwargs.get("extra_body") or {})
            for key in (
                "thinking",
                "reasoning_effort",
                "reasoning_content",
                "mandatory_echo",
                "previous_response_id",
            ):
                body.pop(key, None)
            if body:
                kwargs["extra_body"] = body
            else:
                kwargs.pop("extra_body", None)
        return kwargs
