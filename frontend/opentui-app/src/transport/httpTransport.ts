import axios from "axios";
import { API_BASE, authorizationHeaders } from "../apiClient.ts";
import type { ApprovalDecision } from "../ApprovalDialog.tsx";
import { questionInfoFromParams } from "../questionInfo.ts";
import type { QuestionReply } from "../questionInfo.ts";
import { consumeJsonSseStream } from "../sseParser.ts";
import {
  applyStreamEvent,
  settleActiveMessages,
  type StreamEvent,
  type StreamReduceState,
} from "../streamReducer.ts";
import type { Mode, StatusInfo } from "../types.ts";
import {
  httpCancelActiveRequest,
  httpFetchStatus,
  httpRespondApproval,
  httpRespondQuestion,
  httpSendCommand,
  type CommandResult,
} from "./httpAdmin.ts";
import { applyThoughtExpandedOverride, nextThoughtExpanded } from "../lib/thinkingDisplay.ts";
import { liveProgressText } from "./notifyToStreamEvent.ts";
import { spliceTurnMessages } from "./streamLifecycle.ts";
import { applyTokenUsageToStatus } from "./stdioCommands.ts";
import { looksLikePlanDocument, parsePlanDoc } from "../planDoc.ts";
import type {
  ChatApiCallbacks,
  ChatTransport,
  ChildNavigationEntry,
  ChildNavigationResult,
  SubagentResult,
} from "./types.ts";

function newId(suffix: string): string {
  return `${Date.now()}-${suffix}-${Math.random().toString(36).slice(2, 7)}`;
}

let httpPromptEpoch = 0;

export const httpTransport: ChatTransport = {
  kind: "http",

  async fetchStatus(onStatus: (status: StatusInfo | null) => void): Promise<void> {
    return httpFetchStatus(onStatus);
  },

  async sendCommand(command: string): Promise<CommandResult> {
    return httpSendCommand(command);
  },

  async cancelActiveRequest(): Promise<void> {
    return httpCancelActiveRequest();
  },

  async steerTurn(_text: string, _mode?: import("../types.ts").Mode) {
    return {
      ok: false as const,
      message: "HTTP 传输不支持立即发送（请等当前回合结束，或改用默认 stdio）",
    };
  },

  async respondApproval(approvalId: string, decision: ApprovalDecision): Promise<boolean> {
    return httpRespondApproval(approvalId, decision);
  },

  async respondQuestion(questionId: string, reply: QuestionReply): Promise<boolean> {
    return httpRespondQuestion(questionId, reply);
  },

  async invokeSubagent(agentId: string, prompt: string): Promise<SubagentResult> {
    try {
      const resp = await axios.post<SubagentResult>(
        `${API_BASE}/subagents/invoke`,
        { agent_id: agentId, prompt },
        { headers: authorizationHeaders() },
      );
      return resp.data;
    } catch (err) {
      return {
        request_id: "",
        child_session_id: "",
        status: "failed",
        summary: "",
        artifacts: [],
        evidence: [],
        usage: { steps: 0, input_tokens: 0, output_tokens: 0 },
        error: {
          code: "transport_error",
          message: axios.isAxiosError(err)
            ? String(err.response?.data?.detail ?? err.message)
            : err instanceof Error
              ? err.message
              : "HTTP transport failed",
        },
      };
    }
  },

  async listChildSessions(): Promise<ChildNavigationEntry[]> {
    const result = await httpSendCommand("/children");
    return Array.isArray(result.children)
      ? result.children.filter((item): item is ChildNavigationEntry =>
          typeof item === "object" && item !== null && typeof (item as { session_id?: unknown }).session_id === "string",
        )
      : [];
  },

  async openChildSession(target: string): Promise<ChildNavigationResult> {
    const result = await httpSendCommand(`/child ${target}`);
    return {
      ok: result.ok,
      entry: result.ok ? { session_id: target } : undefined,
      message: String(result.message ?? result.error ?? `child session ${target}`),
    };
  },

  async openParentSession(): Promise<ChildNavigationResult> {
    const result = await httpSendCommand("/parent");
    return { ok: result.ok, message: String(result.message ?? result.error ?? "parent session") };
  },

  async sendChatMessage(
    content: string,
    mode: Mode,
    callbacks: ChatApiCallbacks,
    signal?: AbortSignal,
    displayContent?: string,
  ): Promise<void> {
    const userMsg = {
      id: newId("user"),
      role: "user" as const,
      content: displayContent?.trim() ? displayContent : content,
      timestamp: Date.now(),
      mode,
    };
    httpPromptEpoch += 1;
    const epoch = httpPromptEpoch;
    callbacks.onMessages((prev) => [...prev, userMsg]);
    callbacks.onStreaming(true);
    callbacks.onProgress?.("Connecting...");

    const thinkingId = newId("thinking");
    const assistantId = newId("assistant");

    let state: StreamReduceState = {
      messages: [
        {
          id: thinkingId,
          role: "thinking",
          content: "…",
          timestamp: Date.now(),
          live: true,
          done: false,
          expanded: nextThoughtExpanded(),
        },
      ],
      thinkingId,
      assistantId,
      acc: "",
      assistantCreated: false,
      reasoningAcc: "",
      hasReasoning: false,
    };

    callbacks.onMessages((prev) => [...prev, ...state.messages]);

    const publish = (next: StreamReduceState) => {
      if (httpPromptEpoch !== epoch) return;
      state = {
        ...next,
        messages: next.messages.map(applyThoughtExpandedOverride),
      };
      callbacks.onMessages((prev) => spliceTurnMessages(prev, userMsg.id, state.messages));
    };

    let lastStatus: StatusInfo | null = null;
    let lastLive = "";
    const handleEvent = (event: StreamEvent) => {
      if (event.type === "token_usage" || event.type === "final") {
        lastStatus = applyTokenUsageToStatus(lastStatus, event);
        callbacks.onStatus(lastStatus);
      }
      if (event.type === "plan") {
        callbacks.onPlan?.(parsePlanDoc(String(event.text || ""), event.steps));
      }
      if (event.type === "final" && mode === "plan" && event.text && looksLikePlanDocument(event.text)) {
        callbacks.onPlan?.(parsePlanDoc(event.text));
      }
      const live = liveProgressText(event);
      if (live && live !== lastLive) {
        lastLive = live;
        callbacks.onProgress?.(live);
      }
      if (event.type === "approval_request") {
        const args = event.args;
        callbacks.onApprovalRequest?.({
          approvalId: String(event.approval_id || ""),
          tool: String(event.tool || event.name || "unknown"),
          risk: String(event.risk || "WRITE"),
          args: typeof args === "string" ? args : JSON.stringify(args ?? {}),
        });
      }
      if (event.type === "question_request") {
        callbacks.onQuestionRequest?.(
          questionInfoFromParams({
            question_id: event.question_id,
            question: event.question,
            header: event.header,
            options: event.options,
            input_type: event.input_type,
          }),
        );
      }
      if (event.type === "tool_result") {
        lastLive = "";
        callbacks.onProgress?.("");
        callbacks.onApprovalRequest?.(null);
      }
      const next = applyStreamEvent(state, event, newId);
      if (next !== state) publish(next);
    };

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
      await consumeJsonSseStream<StreamEvent>(
        reader,
        handleEvent,
        (event) => event.type === "final" || event.type === "done",
      );

      publish({
        ...state,
        messages: settleActiveMessages(state.messages),
      });
    } catch (e) {
      if ((e as Error)?.name === "AbortError") {
        publish({
          ...state,
          messages: [
            ...settleActiveMessages(state.messages, "cancelled"),
            {
              id: newId("system"),
              role: "system",
              content: "Cancelled.",
              timestamp: Date.now(),
            },
          ],
        });
      } else {
        callbacks.onMessages((prev) => [
          ...settleActiveMessages(prev),
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
      void httpTransport.fetchStatus(callbacks.onStatus);
    }
  },

  async listSessions() {
    return [];
  },

  async attachSession(sessionId: string) {
    return { session_id: sessionId, messages: [] };
  },

  async renameSession(sessionId: string, title: string) {
    return {
      session_id: sessionId,
      title,
      display_title: title,
      age_label: "now",
      date_group: "Today",
      title_is_manual: true,
    };
  },

  async trashSession() {
    return;
  },

  async pinSession() {
    return;
  },

  async forkSession(sessionId: string) {
    return { session_id: sessionId, display_title: "新任务" };
  },
};
