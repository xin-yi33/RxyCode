import axios from "axios";
import { API_BASE, authorizationHeaders } from "../apiClient.ts";
import { sendCommand } from "../chatApi.ts";
import { type ModelInfo } from "../../../src/fetchModelsProbe.ts";

export type { ModelInfo };

export async function probeModels(): Promise<{
  ok: boolean;
  models: ModelInfo[];
  active: string;
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
  } catch {
    return { ok: false, models: [], active: "" };
  }
}

export async function fetchModels(): Promise<{
  models: ModelInfo[];
  active: string;
  recent: string[];
}> {
  try {
    const resp = await axios.get(`${API_BASE}/models`, {
      timeout: 8000,
      headers: authorizationHeaders(),
    });
    const data = resp.data as { models?: ModelInfo[]; active?: string; recent?: string[] };
    return {
      models: data.models ?? [],
      active: data.active ?? "",
      recent: Array.isArray(data.recent) ? data.recent : [],
    };
  } catch {
    return { models: [], active: "", recent: [] };
  }
}

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

function errorDetail(err: unknown): string {
  if (axios.isAxiosError(err) && typeof err.response?.data?.detail === "string") {
    return err.response.data.detail;
  }
  return err instanceof Error ? err.message : String(err);
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
}): Promise<{ ok: boolean; models: DiscoveredModel[]; error?: string }> {
  try {
    const resp = await axios.post(
      `${API_BASE}/models/discover`,
      { api_key: input.apiKey, base_url: input.baseUrl },
      { headers: authorizationHeaders(), timeout: 60000 },
    );
    const data = resp.data as { models?: DiscoveredModel[] };
    return { ok: true, models: Array.isArray(data.models) ? data.models : [] };
  } catch (err: unknown) {
    return { ok: false, models: [], error: errorDetail(err) };
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
  result: Record<string, unknown> | null,
  kind: "session" | "memory" | "skill" | "mcp" | "queue" | "schedule",
): Array<{ id: string; title: string; description?: string }> {
  if (!result) return [];
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
