/** Pure helpers for when the TUI should leave the Processing state. */

import type { ChatMessage } from "../types.ts";

export type SteerMark = { at: number; msg: ChatMessage };

/** Insert mid-turn steer user bubbles so later stream rows walk them upward. */
export function composeTurnWithSteers(
  turnMessages: ChatMessage[],
  marks: readonly SteerMark[],
): ChatMessage[] {
  if (marks.length === 0) return turnMessages;
  const out: ChatMessage[] = [];
  let i = 0;
  for (const mark of [...marks].sort((a, b) => a.at - b.at)) {
    const take = Math.max(0, mark.at - i);
    out.push(...turnMessages.slice(i, i + take));
    i += take;
    out.push(mark.msg);
  }
  out.push(...turnMessages.slice(i));
  return out;
}

/** Replace one turn's bubbles without deleting later user messages. */
export function spliceTurnMessages(
  prev: ChatMessage[],
  userId: string,
  turnMessages: ChatMessage[],
): ChatMessage[] {
  const start = prev.findIndex((m) => m.id === userId);
  if (start < 0) return prev;
  const turnUserIds = new Set(
    turnMessages.filter((m) => m.role === "user").map((m) => m.id),
  );
  let end = prev.length;
  for (let i = start + 1; i < prev.length; i++) {
    if (prev[i].role === "user" && !turnUserIds.has(prev[i].id)) {
      end = i;
      break;
    }
  }
  return [...prev.slice(0, start + 1), ...turnMessages, ...prev.slice(end)];
}

/** Clear Processing as soon as the turn's terminal stream event arrives. */
export function shouldClearStreamingOnNotify(method: string): boolean {
  return (
    method === "event/final" ||
    method === "event/done" ||
    method === "event/error"
  );
}

/** Esc/Ctrl+C must leave Processing immediately, not after session/prompt returns. */
export function shouldClearStreamingOnUserCancel(): boolean {
  return true;
}

export function abortError(): Error {
  const err = new Error("Aborted");
  err.name = "AbortError";
  return err;
}

/** Stop waiting for session/prompt as soon as Esc aborts; do not wait for worker teardown. */
export function raceWithAbort<T>(
  request: Promise<T>,
  ...signals: Array<AbortSignal | undefined>
): Promise<T> {
  const active = signals.filter((signal): signal is AbortSignal => Boolean(signal));
  if (active.some((signal) => signal.aborted)) {
    return Promise.reject(abortError());
  }
  if (active.length === 0) return request;
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(abortError());
    for (const signal of active) {
      signal.addEventListener("abort", onAbort, { once: true });
    }
    const clear = () => {
      for (const signal of active) {
        signal.removeEventListener("abort", onAbort);
      }
    };
    request.then(
      (value) => {
        clear();
        resolve(value);
      },
      (err) => {
        clear();
        reject(err);
      },
    );
  });
}
