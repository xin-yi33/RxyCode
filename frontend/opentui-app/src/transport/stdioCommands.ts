import type { StatusInfo } from "../types.ts";

export type StdioAdminCommand =
  | { kind: "thinking" }
  | { kind: "model"; modelId: string }
  | { kind: "http"; command: string };

/** Stdio /model must keep the live worker; HTTP /command used to kill it. */
export function shouldRestartStdioSessionOnModelSwitch(): boolean {
  return false;
}

export function parseStdioAdminCommand(command: string): StdioAdminCommand {
  const trimmed = command.trim();
  if (trimmed === "/thinking") {
    return { kind: "thinking" };
  }
  const modelMatch = trimmed.match(/^\/model\s+(\S.*)$/);
  if (modelMatch) {
    return { kind: "model", modelId: modelMatch[1].trim() };
  }
  return { kind: "http", command: trimmed };
}

export type ModelsListPayload = {
  active?: string;
  recent?: string[];
  effort?: string | null;
  models?: Array<{
    id: string;
    name?: string;
    nickname?: string;
    active?: boolean;
    category?: string;
    provider_name?: string;
    base_url?: string;
    context_window?: number | null;
    effort_options?: string[];
  }>;
};

function hostFromUrl(url?: string): string {
  if (!url) return "";
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}

/** Status chip: nickname, plus host when the same nickname exists twice. */
export function statusModelLabel(listed: ModelsListPayload, previousModel?: string): string {
  const activeId =
    listed.active || listed.models?.find((item) => item.active)?.id || "";
  const item = listed.models?.find((entry) => entry.id === activeId);
  const nick = item?.nickname || item?.name || activeId || previousModel || "unknown";
  const raw = item?.nickname || item?.name || "";
  const collisions = raw
    ? (listed.models || []).filter((m) => (m.nickname || m.name || "") === raw).length
    : 0;
  const tag = hostFromUrl(item?.base_url) || item?.category || item?.provider_name || "";
  if (raw && collisions > 1 && tag && !nick.includes(tag)) {
    return `${nick} · ${tag}`;
  }
  return nick;
}

export type TokenUsagePayload = {
  input_tokens?: number | null;
  output_tokens?: number | null;
  cache_hit_tokens?: number | null;
  cache_hit_rate?: number | null;
  reporting_status?: string | null;
  /** Current window occupancy (prompt + this-turn output), not last-turn delta. */
  context_used?: number | null;
};

function asFiniteNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value;
}

function formatCacheSize(tokens: number): string {
  if (tokens <= 0) return "0B";
  if (tokens < 1000) return String(Math.round(tokens));
  if (tokens < 1_000_000) return `${(tokens / 1000).toFixed(1)}K`;
  return `${(tokens / 1_000_000).toFixed(2)}M`;
}

/** Map a protocol usage payload onto the OpenTUI status bar fields. */
export function applyTokenUsageToStatus(
  previous: StatusInfo | null | undefined,
  usage: TokenUsagePayload,
): StatusInfo {
  const base = { ...(previous ?? {}) };
  if (usage.reporting_status === "not_reported") {
    return base;
  }
  const input = asFiniteNumber(usage.input_tokens);
  const output = asFiniteNumber(usage.output_tokens);
  const cacheHit = asFiniteNumber(usage.cache_hit_tokens);
  const cacheRate = asFiniteNumber(usage.cache_hit_rate);
  const windowUsed = asFiniteNumber(usage.context_used);
  if (
    input == null &&
    output == null &&
    cacheHit == null &&
    cacheRate == null &&
    windowUsed == null
  ) {
    return base;
  }
  // Occupancy is context_used only (same occupancy_tokens as compact).
  // Billing input+output includes cached prefix and is never occupancy.
  const occupancy =
    windowUsed != null && windowUsed > 0
      ? windowUsed
      : Math.round((base.context_used_k ?? 0) * 1000);
  return {
    ...base,
    input_tokens: input ?? base.input_tokens,
    output_tokens: output ?? base.output_tokens,
    context_used_k: occupancy > 0 ? Math.round(occupancy / 100) / 10 : (base.context_used_k ?? 0),
    cache_size: cacheHit != null ? formatCacheSize(cacheHit) : (base.cache_size ?? "0B"),
    cache_rate:
      cacheRate != null ? `${cacheRate.toFixed(1)}%` : (base.cache_rate ?? "0.0%"),
  };
}

/** Header/status model from config, not from a lazily started HTTP agent. */
export function statusFromModelsList(
  listed: ModelsListPayload,
  previous?: StatusInfo | null,
): StatusInfo {
  const activeId =
    listed.active || listed.models?.find((item) => item.active)?.id || "";
  const item = listed.models?.find((entry) => entry.id === activeId);
  const model = statusModelLabel(listed, previous?.model);
  const window = item?.context_window;
  const contextMaxK =
    typeof window === "number" && window > 0
      ? Math.round(window / 1000)
      : previous?.context_max_k;
  const effortRaw = typeof listed.effort === "string" ? listed.effort.trim() : "";
  return {
    ...(previous ?? {}),
    model,
    ...(contextMaxK != null ? { context_max_k: contextMaxK } : {}),
    effort: effortRaw || previous?.effort,
  };
}
