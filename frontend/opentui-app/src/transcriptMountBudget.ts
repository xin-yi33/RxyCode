import type { ChatMessage } from "./types.ts";

export const DEFAULT_TRANSCRIPT_MOUNT_BUDGET = 80;
export const TRANSCRIPT_HISTORY_PAGE_SIZE = 40;

export interface TranscriptMountRange {
  start: number;
  end: number;
}

function normalizedCount(value: number): number {
  return Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
}

export function tailTranscriptRange(
  messageCount: number,
  budget = DEFAULT_TRANSCRIPT_MOUNT_BUDGET,
): TranscriptMountRange {
  const count = normalizedCount(messageCount);
  const size = Math.max(1, normalizedCount(budget));
  return { start: Math.max(0, count - size), end: count };
}

export function olderTranscriptRange(
  range: TranscriptMountRange,
  messageCount: number,
  budget = DEFAULT_TRANSCRIPT_MOUNT_BUDGET,
  pageSize = TRANSCRIPT_HISTORY_PAGE_SIZE,
): TranscriptMountRange {
  const count = normalizedCount(messageCount);
  const size = Math.max(1, normalizedCount(budget));
  const page = Math.max(1, normalizedCount(pageSize));
  const start = Math.max(0, Math.min(range.start, count) - page);
  if (start === range.start) return range;
  return { start, end: Math.min(count, start + size) };
}

export function newerTranscriptRange(
  range: TranscriptMountRange,
  messageCount: number,
  budget = DEFAULT_TRANSCRIPT_MOUNT_BUDGET,
  pageSize = TRANSCRIPT_HISTORY_PAGE_SIZE,
): TranscriptMountRange {
  const count = normalizedCount(messageCount);
  const size = Math.max(1, normalizedCount(budget));
  const page = Math.max(1, normalizedCount(pageSize));
  if (range.end >= count) return tailTranscriptRange(count, size);
  const end = Math.min(count, range.end + page);
  return { start: Math.max(0, end - size), end };
}

export function sameTranscriptRange(
  left: TranscriptMountRange,
  right: TranscriptMountRange,
): boolean {
  return left.start === right.start && left.end === right.end;
}

/** Keep /copy independent of the mounted OpenTUI window. */
export function formatAllMessagesForCopy(messages: readonly ChatMessage[]): string {
  const lines: string[] = [];
  for (const message of messages) {
    if (message.role === "user") lines.push(`> ${message.content}`);
    else if (message.role === "assistant") lines.push(message.content);
    else if (message.role === "thinking") lines.push(`[思考] ${message.content}`);
    else if (message.role === "tool") {
      const name = message.toolName || "tool";
      const status = message.toolStatus || "running";
      const args = message.toolArgs ? ` ${message.toolArgs}` : "";
      lines.push(`[${name} ${status}]${args} ${message.content || ""}`);
    } else if (message.role === "system") lines.push(`[系统] ${message.content}`);
    else if (message.role === "child_session") {
      lines.push(`[子代理 ${message.agentId || ""}] ${message.content}`);
    }
  }
  return lines.join("\n").trim();
}
