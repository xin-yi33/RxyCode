import axios from "axios";
import { API_BASE, authorizationHeaders } from "../apiClient.ts";
import { sendCommand } from "../chatApi.ts";

export type ModelInfo = {
  id: string;
  name: string;
  nickname?: string;
  provider_model_id?: string;
  base_url?: string;
  active?: boolean;
  category?: string;
  provider_name?: string;
  provider_id?: string;
  // Phase 3 M6：可选输出上限摘要（旧服务器缺失�?undefined�?/
  max_tokens_mode?: "auto" | "explicit";
  resolved_max_tokens?: number;
  limit_source?: string;
  context_window?: number | null;
  warning?: string | null;
  // /effort 扩展（2026-08-12）：该模型的厂商档位全集（空 = 不支持档位选择）。
  effort_options?: string[];
};

export async function probeModels(): Promise<{
  ok: boolean;
  models: ModelInfo[];
  active: string;
  error?: string;
}> {
  try {
    const resp = await axios.get(`${API_BASE}/models`, {
      timeout: 8000,
      headers: authorizationHeaders(),
    });
    const data = resp.data as { models?: ModelInfo[]; active?: string };
    return {
      ok: true,
      models: data.models ?? [],
      active: data.active ?? "",
    };
  } catch (err: unknown) {
    return {
      ok: false,
      models: [],
      active: "",
      error: err instanceof Error ? err.message : "无法连接 API 服务",
    };
  }
}

export async function fetchModels(): Promise<{
  ok: boolean;
  models: ModelInfo[];
  active: string;
  recent: string[];
  effort: string | null;
  error?: string;
}> {
  try {
    const { resolveTransportKind } = await import("../transport/config.ts");
    if (resolveTransportKind() === "stdio") {
      const { isStdioSessionReady, listStdioModels } = await import(
        "../transport/stdioTransport.ts"
      );
      if (isStdioSessionReady()) {
        const listed = await listStdioModels();
        const effortRaw = typeof listed.effort === "string" ? listed.effort.trim() : "";
        return {
          ok: true,
          models: (listed.models ?? []) as ModelInfo[],
          active: listed.active ?? "",
          recent: Array.isArray(listed.recent) ? listed.recent : [],
          effort: effortRaw || null,
        };
      }
    }
  } catch {
    // Fall through to HTTP for hybrid / tests.
  }
  try {
    const resp = await axios.get(`${API_BASE}/models`, {
      timeout: 8000,
      headers: authorizationHeaders(),
    });
    const data = resp.data as {
      models?: ModelInfo[];
      active?: string;
      recent?: string[];
      effort?: string | null;
    };
    const effortRaw = typeof data.effort === "string" ? data.effort.trim() : "";
    return {
      ok: true,
      models: data.models ?? [],
      active: data.active ?? "",
      recent: Array.isArray(data.recent) ? data.recent : [],
      effort: effortRaw || null,
    };
  } catch (err: unknown) {
    return {
      ok: false,
      models: [],
      active: "",
      recent: [],
      effort: null,
      error: err instanceof Error ? err.message : "无法连接 API 服务",
    };
  }
}

/** Same list as fetchModels, plus the persisted effort chip value. */
export async function fetchEffortOptions(): Promise<{
  ok: boolean;
  models: ModelInfo[];
  active: string;
  effort: string | null;
  error?: string;
}> {
  const listed = await fetchModels();
  if (!listed.ok) {
    return {
      ok: false,
      models: [],
      active: "",
      effort: null,
      error: listed.error,
    };
  }
  return {
    ok: true,
    models: listed.models,
    active: listed.active,
    effort: listed.effort,
  };
}

// 废弃代码（2026-09-21）：fetchEffortOptions 旧实现只打 HTTP GET /models，
// stdio TUI 会读到另一进程、档位列表空。禁止再作为主路径引用。
// export async function fetchEffortOptions(): Promise<{
//   ok: boolean;
//   models: ModelInfo[];
//   active: string;
//   effort: string | null;
//   error?: string;
// }> {
//   try {
//     const resp = await axios.get(`${API_BASE}/models`, {
//       timeout: 8000,
//       headers: authorizationHeaders(),
//     });
//     const data = resp.data as {
//       models?: ModelInfo[];
//       active?: string;
//       effort?: string | null;
//     };
//     return {
//       ok: true,
//       models: data.models ?? [],
//       active: data.active ?? "",
//       effort: typeof data.effort === "string" && data.effort ? data.effort : null,
//     };
//   } catch (err: unknown) {
//     return {
//       ok: false,
//       models: [],
//       active: "",
//       effort: null,
//       error: err instanceof Error ? err.message : "无法连接 API 服务",
//     };
//   }
// }

/**
 * A connection preset: provider + base URL only.
 * Model ids are never presets — they come from discoverModels() or user input.
 */
export type ProviderPreset = {
  id: string;
  name: string;
  base_url: string;
  category?: string;
};

export type DiscoveredModel = {
  id: string;
  owned_by?: string;
};

/** Stable discover failure codes — keep in sync with config.model_manager. */
export type DiscoverErrorCode =
  | "unsupported_catalogue"
  | "auth"
  | "https"
  | "invalid"
  | "transport";

const DISCOVER_ERROR_CODES = new Set<DiscoverErrorCode>([
  "unsupported_catalogue",
  "auth",
  "https",
  "invalid",
  "transport",
]);

function errorDetail(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const message = (detail as { message?: unknown }).message;
      if (typeof message === "string" && message) return message;
    }
  }
  return err instanceof Error ? err.message : String(err);
}

function discoveryFailure(err: unknown): {
  message: string;
  errorCode: DiscoverErrorCode;
} {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const code = String((detail as { error_code?: unknown }).error_code ?? "");
      const message = String(
        (detail as { message?: unknown }).message || errorDetail(err),
      );
      return {
        message,
        errorCode: DISCOVER_ERROR_CODES.has(code as DiscoverErrorCode)
          ? (code as DiscoverErrorCode)
          : "transport",
      };
    }
  }
  return { message: errorDetail(err), errorCode: "transport" };
}

/** GET /models/presets — provider connection presets (no model ids). */
export async function fetchProviderPresets(): Promise<{
  ok: boolean;
  presets: ProviderPreset[];
  error?: string;
}> {
  try {
    const resp = await axios.get(`${API_BASE}/models/presets`, {
      timeout: 8000,
      headers: authorizationHeaders(),
    });
    const data = resp.data as { presets?: ProviderPreset[] };
    return { ok: true, presets: Array.isArray(data.presets) ? data.presets : [] };
  } catch (err: unknown) {
    return { ok: false, presets: [], error: errorDetail(err) };
  }
}

/**
 * POST /models/discover — ask the provider which models the key can use.
 * Read-only on the backend: nothing is persisted until onboardModel().
 */
export async function discoverModels(input: {
  apiKey: string;
  baseUrl: string;
}): Promise<{
  ok: boolean;
  models: DiscoveredModel[];
  error?: string;
  errorCode?: DiscoverErrorCode;
}> {
  try {
    const resp = await axios.post(
      `${API_BASE}/models/discover`,
      { api_key: input.apiKey, base_url: input.baseUrl },
      { headers: authorizationHeaders(), timeout: 60000 },
    );
    const data = resp.data as { models?: DiscoveredModel[] };
    return { ok: true, models: Array.isArray(data.models) ? data.models : [] };
  } catch (err: unknown) {
    const failure = discoveryFailure(err);
    return {
      ok: false,
      models: [],
      error: failure.message,
      errorCode: failure.errorCode,
    };
  }
}

export async function onboardModel(input: {
  providerModelId: string;
  apiKey: string;
  baseUrl: string;
  nickname?: string;
}): Promise<Record<string, unknown>> {
  try {
    const resp = await axios.post(
      `${API_BASE}/models/onboard`,
      {
        provider_model_id: input.providerModelId,
        nickname: input.nickname || undefined,
        api_key: input.apiKey,
        base_url: input.baseUrl,
      },
      { headers: authorizationHeaders(), timeout: 60000 },
    );
    return (resp.data ?? {}) as Record<string, unknown>;
  } catch (err: unknown) {
    const detail =
      axios.isAxiosError(err) && typeof err.response?.data?.detail === "string"
        ? err.response.data.detail
        : err instanceof Error
          ? err.message
          : String(err);
    return { action: "error", message: detail };
  }
}

export async function onboardModelsBatch(input: {
  apiKey: string;
  baseUrl: string;
  modelIds: string[];
  providerId?: string;
  providerName?: string;
  activeModelId?: string;
  skipProbe?: boolean;
}): Promise<{
  ok: boolean;
  added: string[];
  skipped: string[];
  active: string;
  message: string;
  error?: string;
}> {
  try {
    const resp = await axios.post(
      `${API_BASE}/models/onboard/batch`,
      {
        api_key: input.apiKey,
        base_url: input.baseUrl,
        model_ids: input.modelIds,
        provider_id: input.providerId || undefined,
        provider_name: input.providerName || undefined,
        active_model_id: input.activeModelId || undefined,
        skip_probe: input.skipProbe ?? true,
      },
      { headers: authorizationHeaders(), timeout: 60000 },
    );
    const data = resp.data as {
      added?: string[];
      skipped?: string[];
      active?: string;
      message?: string;
    };
    return {
      ok: true,
      added: Array.isArray(data.added) ? data.added : [],
      skipped: Array.isArray(data.skipped) ? data.skipped : [],
      active: String(data.active || ""),
      message: String(data.message || "Models added"),
    };
  } catch (err: unknown) {
    return {
      ok: false,
      added: [],
      skipped: [],
      active: "",
      message: "",
      error: errorDetail(err),
    };
  }
}

export { sendCommand };

/** GET /status raw payload (includes provider_cache / application_cache when present). */
export async function fetchStatusPayload(): Promise<Record<string, unknown> | null> {
  try {
    const resp = await axios.get(`${API_BASE}/status`, {
      timeout: 5000,
      headers: authorizationHeaders(),
    });
    return (resp.data ?? null) as Record<string, unknown> | null;
  } catch {
    return null;
  }
}

/** Normalize /command list payloads into DialogSelect options. */
export function listFromCommandResult(
  result: Record<string, unknown> | null | undefined,
  kind: "session" | "memory" | "skill" | "mcp" | "queue" | "schedule",
): Array<{ id: string; title: string; description?: string }> {
  if (!result || result.ok === false) return [];
  if (kind === "session") {
    const chats = (result.chats as Array<{ name?: string; preview?: string; time?: string }>) || [];
    return chats.map((c) => ({
      id: String(c.name || ""),
      title: String(c.name || ""),
      description: c.time ? String(c.time) : String(c.preview || ""),
    }));
  }
  if (kind === "memory") {
    const memories = (result.memories as Array<{ id?: string | number; text?: string }>) || [];
    return memories.map((m) => ({
      id: String(m.id ?? ""),
      title: `[${m.id}]`,
      description: String(m.text || ""),
    }));
  }
  if (kind === "skill") {
    const skills = (result.skills as Array<{ name?: string; id?: string; description?: string }>) || [];
    return skills.map((s) => ({
      id: String(s.name || s.id || ""),
      title: String(s.name || s.id || ""),
      description: String(s.description || ""),
    }));
  }
  if (kind === "mcp") {
    const servers =
      (result.servers as Array<{ name?: string; command?: string }>) ||
      (result.mcps as Array<{ name?: string; command?: string }>) ||
      [];
    return servers.map((s) => ({
      id: String(s.name || ""),
      title: String(s.name || ""),
      description: String(s.command || ""),
    }));
  }
  const tasks = (result.tasks as Array<{ id?: string; prompt?: string }>) || [];
  return tasks.map((t) => ({
    id: String(t.id || ""),
    title: `[${t.id}]`,
    description: String(t.prompt || ""),
  }));
}
