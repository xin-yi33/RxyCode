import axios from "axios";
import { API_BASE, authorizationHeaders } from "./apiClient.ts";
import { consumeJsonSseStream } from "./sseParser.ts";
import type { ChatMessage, Mode, StatusInfo, ToolStatus } from "./types.ts";

interface StreamEvent {
  type: string;
  text?: string;
  thinking?: string;
  message?: string;
  name?: string;
  args?: string;
  result?: string;
  status?: string;
  exitCode?: number;
  duration?: number;
  error?: string;
  snapshot?: boolean;
}

export type MessageUpdater = (prev: ChatMessage[]) => ChatMessage[];

export interface ChatApiCallbacks {
  onMessages: (updater: MessageUpdater) => void;
  onStreaming: (streaming: boolean) => void;
  onStatus: (status: StatusInfo | null) => void;
  onProgress?: (text: string) => void;
}

function newId(suffix: string): string {
  return `${Date.now()}-${suffix}-${Math.random().toString(36).slice(2, 7)}`;
}

export async function fetchStatus(onStatus: (status: StatusInfo | null) => void): Promise<void> {
  try {
    const resp = await axios.get(`${API_BASE}/status`, {
      timeout: 5000,
      headers: authorizationHeaders(),
    });
    onStatus(resp.data as StatusInfo);
  } catch {
    onStatus(null);
  }
}

/** POST /command — same contract as Ink useApi.sendCommand (U3 /thinking gate sync). */
export async function sendCommand(command: string): Promise<Record<string, unknown> | null> {
  try {
    const resp = await axios.post(
      `${API_BASE}/command`,
      { command },
      { headers: authorizationHeaders(), timeout: 15000 },
    );
    return (resp.data ?? null) as Record<string, unknown> | null;
  } catch {
    return null;
  }
}

export async function sendChatMessage(
  content: string,
  mode: Mode,
  callbacks: ChatApiCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const userMsg: ChatMessage = {
    id: newId("user"),
    role: "user",
    content,
    timestamp: Date.now(),
  };
  callbacks.onMessages((prev) => [...prev, userMsg]);
  callbacks.onStreaming(true);
  callbacks.onProgress?.("Connecting...");

  const thinkingId = newId("thinking");
  const assistantId = newId("assistant");
  let acc = "";
  let assistantCreated = false;
  let reasoningAcc = "";
  let hasReasoning = false;

  callbacks.onMessages((prev) => [
    ...prev,
    {
      id: thinkingId,
      role: "thinking",
      content: "…",
      timestamp: Date.now(),
      live: true,
      done: false,
    },
  ]);

  try {
    let resp: Response | null = null;
    let lastErr: unknown = null;
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        resp = await fetch(`${API_BASE}/chat/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authorizationHeaders() },
          body: JSON.stringify({ message: content, mode }),
          signal,
        });
        lastErr = null;
        break;
      } catch (e) {
        lastErr = e;
        if (attempt === 0) await new Promise((r) => setTimeout(r, 1500));
      }
    }

    if (!resp) {
      throw lastErr instanceof Error ? lastErr : new Error(String(lastErr));
    }
    if (!resp.ok || !resp.body) {
      throw new Error(`Chat stream failed: HTTP ${resp.status}`);
    }

    const reader = resp.body.getReader();
    let finalText: string | undefined;

    await consumeJsonSseStream<StreamEvent>(
      reader,
      (event) => {
        switch (event.type) {
          case "progress":
            if (!hasReasoning) {
              callbacks.onProgress?.(event.message || event.text || "Working...");
            }
            break;
          case "reasoning":
          case "thinking": {
            const thought = event.thinking || event.text || "";
            if (!thought) break;
            if (event.snapshot || !hasReasoning) {
              reasoningAcc = thought;
            } else {
              reasoningAcc += thought;
            }
            hasReasoning = true;
            callbacks.onMessages((prev) =>
              prev.map((m) =>
                m.id === thinkingId
                  ? { ...m, content: reasoningAcc, live: true, done: false }
                  : m,
              ),
            );
            break;
          }
          case "token":
            if (event.text) {
              acc += event.text;
              if (!assistantCreated) {
                assistantCreated = true;
                callbacks.onMessages((prev) => [
                  ...prev.map((m) =>
                    m.id === thinkingId ? { ...m, done: true, live: false, content: m.content === "…" ? "done" : m.content } : m,
                  ),
                  {
                    id: assistantId,
                    role: "assistant",
                    content: acc,
                    timestamp: Date.now(),
                    done: false,
                  },
                ]);
              } else {
                callbacks.onMessages((prev) =>
                  prev.map((m) => (m.id === assistantId ? { ...m, content: acc } : m)),
                );
              }
            }
            break;
          case "tool_call":
            callbacks.onMessages((prev) => [
              ...prev,
              {
                id: newId("tool"),
                role: "tool",
                content: event.args || "",
                timestamp: Date.now(),
                toolName: event.name || "tool",
                toolStatus: "running",
              },
            ]);
            callbacks.onProgress?.(event.name ? `Tool: ${event.name}` : "Running tool...");
            break;
          case "tool_result": {
            const status: ToolStatus =
              event.status === "error" || event.status === "timeout" || event.status === "cancelled"
                ? (event.status as ToolStatus)
                : "success";
            callbacks.onMessages((prev) => {
              const idx = [...prev].reverse().findIndex(
                (m) => m.role === "tool" && m.toolName === (event.name || m.toolName) && m.toolStatus === "running",
              );
              if (idx < 0) return prev;
              const realIdx = prev.length - 1 - idx;
              const next = [...prev];
              next[realIdx] = {
                ...next[realIdx],
                toolStatus: status,
                content: event.result || event.error || next[realIdx].content,
              };
              return next;
            });
            break;
          }
          case "final":
            finalText = event.text ?? event.message ?? acc;
            break;
          case "error":
            callbacks.onMessages((prev) => [
              ...prev,
              {
                id: newId("system"),
                role: "system",
                content: event.error || event.message || "Request failed",
                timestamp: Date.now(),
              },
            ]);
            break;
          default:
            break;
        }
      },
      (event) => event.type === "final" || event.type === "done",
    );

    const resolved = finalText !== undefined ? finalText : acc;
    callbacks.onMessages((prev) => {
      let next = prev.map((m) => {
        if (m.id === thinkingId) return { ...m, done: true, live: false };
        if (m.id === assistantId) return { ...m, content: resolved, done: true };
        return m;
      });
      if (!assistantCreated && resolved) {
        next = [
          ...next,
          {
            id: assistantId,
            role: "assistant",
            content: resolved,
            timestamp: Date.now(),
            done: true,
          },
        ];
      }
      return next;
    });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") {
      callbacks.onMessages((prev) => [
        ...prev.map((m) =>
          m.id === thinkingId || (m.role === "assistant" && m.done !== true)
            ? { ...m, done: true, live: false }
            : m,
        ),
        {
          id: newId("system"),
          role: "system",
          content: "Cancelled.",
          timestamp: Date.now(),
        },
      ]);
    } else {
      callbacks.onMessages((prev) => [
        ...prev,
        {
          id: newId("system"),
          role: "system",
          content: e instanceof Error ? e.message : String(e),
          timestamp: Date.now(),
        },
      ]);
    }
  } finally {
    callbacks.onStreaming(false);
    callbacks.onProgress?.("");
    void fetchStatus(callbacks.onStatus);
  }
}
