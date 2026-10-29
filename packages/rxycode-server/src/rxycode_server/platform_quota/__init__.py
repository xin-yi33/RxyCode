"""Platform-funded free quota (deepseek-v4.1-flash via OpenCode Go).

Ten pre-seeded ``platform_grants`` slots are claimed atomically at
registration (and by ``scripts/platform_slots.py`` for existing users).
The platform credential lives only in the worker's parent process: the
run snapshot it issues names ``credential_source="platform"`` and the
confined child always talks to the loopback gateway — the real key is
injected upstream by ``rxycode_worker.egress`` and never enters the
child environment, config, events, or responses.
"""

from rxycode_server.platform_quota.service import (
    PLATFORM_DISPLAY_NAME,
    PLATFORM_EXHAUSTED_TEXT,
    PLATFORM_MODEL_ID,
    PLATFORM_MODEL_REF,
    PLATFORM_PROVIDER_ID,
    PLATFORM_PROVIDER_NAME,
    PLATFORM_SLOT_COUNT,
    PLATFORM_TOKEN_CAP,
    PlatformQuotaRefused,
    backfill_grants,
    check_admission,
    claim_slot,
    env_api_key,
    env_base_url,
    grant_active,
    grant_for_user,
    platform_catalog_item,
    platform_snapshot,
    quota_json,
    remaining,
    settle_grant,
    slot_state,
)

__all__ = [
    "PLATFORM_DISPLAY_NAME",
    "PLATFORM_EXHAUSTED_TEXT",
    "PLATFORM_MODEL_ID",
    "PLATFORM_MODEL_REF",
    "PLATFORM_PROVIDER_ID",
    "PLATFORM_PROVIDER_NAME",
    "PLATFORM_SLOT_COUNT",
    "PLATFORM_TOKEN_CAP",
    "PlatformQuotaRefused",
    "backfill_grants",
    "check_admission",
    "claim_slot",
    "env_api_key",
    "env_base_url",
    "grant_active",
    "grant_for_user",
    "platform_catalog_item",
    "platform_snapshot",
    "quota_json",
    "remaining",
    "settle_grant",
    "slot_state",
]
