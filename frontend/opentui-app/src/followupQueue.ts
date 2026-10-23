/** Follow-up prompts queued while a turn is already in flight. */

import type { Mode } from "./types.ts";
import type { ClipboardAttachment } from "./clipboard.ts";

export const FOLLOWUP_LIMIT = 10;

export type FollowupItem = {
  id: string;
  text: string;
  /** Mode stamped at enqueue time — drain must not use the live Tab. */
  mode: Mode;
  /** Immutable, lightweight file references captured when this item was queued. */
  attachments?: ClipboardAttachment[];
};

export function newFollowupId(): string {
  return `q-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function enqueueFollowup(
  queue: readonly FollowupItem[],
  text: string,
  mode: Mode = "build",
  attachments: readonly ClipboardAttachment[] = [],
): FollowupItem[] {
  const trimmed = text.trim();
  if (!trimmed && attachments.length === 0) return [...queue];
  if (queue.length >= FOLLOWUP_LIMIT) return [...queue];
  return [...queue, {
    id: newFollowupId(),
    text: trimmed || "请查看附件。",
    mode,
    ...(attachments.length ? { attachments: attachments.map((item) => ({ ...item })) } : {}),
  }];
}

export function takeNextFollowup(
  queue: readonly FollowupItem[],
): { item: FollowupItem | null; remaining: FollowupItem[] } {
  if (queue.length === 0) return { item: null, remaining: [] };
  const [item, ...remaining] = queue;
  return { item, remaining };
}

export function takeFollowupById(
  queue: readonly FollowupItem[],
  id: string,
): { item: FollowupItem | null; remaining: FollowupItem[] } {
  const item = queue.find((row) => row.id === id) ?? null;
  return { item, remaining: queue.filter((row) => row.id !== id) };
}

export function removeFollowup(
  queue: readonly FollowupItem[],
  id: string,
): FollowupItem[] {
  return queue.filter((row) => row.id !== id);
}

/** Put an edited draft back (front) so a second Edit does not drop the first. */
export function putBackFollowup(
  queue: readonly FollowupItem[],
  item: FollowupItem | null,
): FollowupItem[] {
  if (!item || (!item.text.trim() && !item.attachments?.length)) return [...queue];
  const without = queue.filter((row) => row.id !== item.id);
  if (without.length >= FOLLOWUP_LIMIT) return without;
  return [{
    ...item,
    text: item.text.trim(),
    ...(item.attachments ? { attachments: item.attachments.map((attachment) => ({ ...attachment })) } : {}),
  }, ...without];
}

export function previewFollowup(text: string, max = 48): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  if (collapsed.length <= max) return collapsed;
  return `${collapsed.slice(0, Math.max(1, max - 1))}…`;
}
