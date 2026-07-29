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

export async function fetchModels(): Promise<{ models: ModelInfo[]; active: string }> {
  try {
    const resp = await axios.get(`${API_BASE}/models`, {
      timeout: 8000,
      headers: authorizationHeaders(),
    });
    const data = resp.data as { models?: ModelInfo[]; active?: string };
    return { models: data.models ?? [], active: data.active ?? "" };
  } catch {
    return { models: [], active: "" };
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
