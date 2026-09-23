"""Muse Spark strategy for Meta Model API and OpenCode Go.

OpenCode Go exposes ``muse-spark-1.2-contributor`` through OpenAI Responses.
The provider therefore owns both family recognition and the exact transport
choice; AgentV2 only consumes the generic ``uses_responses_api`` seam.

Sources (checked 2026-08-24):
  - https://opencode.ai/docs/go/
  - https://ai.developer.meta.com/docs/models/
"""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlsplit

from ._compat import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    ModelPricing,
    UsageFieldMap,
)

from .base import BaseProvider, CHAT_TRANSPORT, RESPONSES_TRANSPORT


_KNOWN_MODELS = frozenset(
    {
        "muse-spark-1.1",
        "muse-spark-1.2",
        "muse-spark-1.2-contributor",
    }
)

_USAGE = UsageFieldMap(
    cache_read_flat=(),
    # Responses uses input_tokens_details; Meta Chat Completions uses
    # prompt_tokens_details.  Keep both because the provider supports a direct
    # Meta endpoint as well as the OpenCode Go route.
    cache_read_nested=(
        ("input_tokens_details", "cached_tokens"),
        ("input_token_details", "cache_read"),
        ("prompt_tokens_details", "cached_tokens"),
    ),
    cache_write_flat=(),
    cache_write_nested=(),
    reasoning_nested=(
        ("output_tokens_details", "reasoning_tokens"),
        ("completion_tokens_details", "reasoning_tokens"),
    ),
    reasoning=("reasoning_content",),
)

_OPENCODE_GO_URL = "https://opencode.ai/docs/go/"

_CONTRIBUTOR_PRICING = ModelPricing(
    input_per_mtok=0.10,
    output_per_mtok=0.20,
    cached_input_per_mtok=0.002,
    cache_write_per_mtok=None,
    as_of="2026-08-24",
    source_url=_OPENCODE_GO_URL,
)
_UNKNOWN_PRICING = ModelPricing()


def _host(base_url: str) -> str:
    try:
        return (urlsplit(base_url).hostname or "").casefold()
    except ValueError:
        return ""


class MuseSparkProvider(BaseProvider):
    """Provider policy for the hosted Muse Spark family."""

    name = "muse_spark"

    def matches(self, base_url: str, model_name: str) -> bool:
        # A shared gateway host cannot identify a family.  Match the narrow
        # family prefix and deliberately exclude Muse Glimmer / Llama.
        return str(model_name or "").strip().casefold().startswith("muse-spark-")

    def transport_candidates(self, model_config: dict) -> tuple[str, ...]:
        # OpenCode Go's official endpoint table pins only the Contributor ID to
        # /v1/responses. Family recognition is intentionally broader than this
        # gateway availability/transport decision.
        pinned = self._resource_path_candidates(model_config)
        if pinned is not None:
            return pinned
        explicit = self.explicit_transport_candidates(model_config)
        if explicit is not None:
            return explicit
        model_name = str(model_config.get("model_name") or "").strip().casefold()
        if (
            _host(str(model_config.get("base_url") or "")) == "opencode.ai"
            and model_name == "muse-spark-1.2-contributor"
        ):
            # Responses is the documented route.  Chat is only an endpoint-
            # mismatch fallback and is never tried for policy/auth/rate errors.
            return (RESPONSES_TRANSPORT, CHAT_TRANSPORT)
        return super().transport_candidates(model_config)

    def reasoning_effort_when_disabled(self, model_config: dict) -> str | None:
        # OpenCode Go does not currently document a Muse effort request
        # contract. Omission preserves the verified Responses request shape.
        return None

    def validate_tool_payloads(self, tools: list[dict]) -> None:
        # Keep the upstream compatibility limit recorded by the project
        # research. Fail locally with the exact offending tool instead of
        # relying on a generic upstream rejection.
        for index, tool in enumerate(tools):
            function = tool.get("function") if isinstance(tool, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            if isinstance(name, str) and len(name) > 64:
                raise ValueError(
                    "Muse Spark function tool names must be at most 64 "
                    f"characters; tools[{index}] has {len(name)} characters"
                )

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        model_name = str(model_config.get("model_name") or "").strip().casefold()
        known = model_name in _KNOWN_MODELS
        pricing = _UNKNOWN_PRICING
        if model_name == "muse-spark-1.2-contributor" and self.uses_responses_api(
            model_config
        ):
            pricing = _CONTRIBUTOR_PRICING

        # Exact Meta limits and Go-side limits are not publicly reproducible.
        # Preserve family recognition while keeping numeric limits conservative.
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            supports_reasoning=known,
            thinking_default_on=False,
            supports_prompt_cache=self.uses_responses_api(model_config),
            cache_breakpoints=(),
            usage_fields=_USAGE,
            pricing=pricing,
        )
        return caps.merged_with_overrides(model_config)

    def llm_kwargs(self, model_config: dict, caps: ModelCapabilities) -> dict:
        kwargs = super().llm_kwargs(model_config, caps)

        body = dict(kwargs.get("extra_body") or {})
        user_body = model_config.get("extra_body")
        if isinstance(user_body, dict):
            body.update(user_body)
        # Do not forward generic or historically documented direct-endpoint
        # reasoning parameters to OpenCode Go without a gateway contract.
        body.pop("thinking", None)
        body.pop("reasoning_effort", None)

        body_temperature = body.pop("temperature", None)
        if body:
            kwargs["extra_body"] = body
        else:
            kwargs.pop("extra_body", None)

        kwargs.pop("reasoning_effort", None)

        # RxyCode stores 0.7 even when the user did not choose a temperature;
        # Meta recommends leaving temperature unset.  Preserve a genuinely
        # explicit value, including an explicitly requested 0.7.
        configured_temperature = model_config.get("temperature", 0.7)
        temperature_explicit = bool(model_config.get("temperature_explicit"))
        if body_temperature is not None:
            kwargs["temperature"] = body_temperature
        elif temperature_explicit or configured_temperature != 0.7:
            kwargs["temperature"] = configured_temperature
        else:
            kwargs.pop("temperature", None)

        if self.uses_responses_api(model_config):
            kwargs["use_responses_api"] = True
        return kwargs
