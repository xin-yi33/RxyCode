import { ToggleCounter } from "./toggleCounter.ts";

const thinkingToggle = new ToggleCounter();
// INVARIANT: a finished Thought keeps its body. Do not start this counter at 0.
// Ctrl+T still toggles. Even counts collapse; the default must be odd/expanded.
// 废弃代码（2026-09-22）：不 increment，停在 0。思考结束时正文被收掉，
// 首位 Thought 看起来消失了。禁止再改回折叠默认。
thinkingToggle.increment();
const expandedById = new Map<string, boolean>();

export function nextThoughtExpanded(): boolean {
  return thinkingToggle.expanded;
}

export function thinkingDisplayExpanded(): boolean {
  return thinkingToggle.expanded;
}

export function thinkingDisplayCount(): number {
  return thinkingToggle.count;
}

export function cycleThinkingDisplay(): { count: number; expanded: boolean } {
  thinkingToggle.increment();
  return { count: thinkingToggle.count, expanded: thinkingToggle.expanded };
}

export function resetThinkingDisplay(): void {
  thinkingToggle.reset();
  // Same default as module load: expanded. Do not leave the counter at 0.
  thinkingToggle.increment();
  expandedById.clear();
}

export function setThoughtExpandedOverride(id: string, expanded: boolean): void {
  expandedById.set(id, expanded);
}

export function getThoughtExpandedOverride(id: string): boolean | undefined {
  return expandedById.get(id);
}

export function applyThoughtExpandedOverride<T extends { id: string; role: string; expanded?: boolean }>(
  msg: T,
): T {
  if (msg.role !== "thinking") return msg;
  const override = expandedById.get(msg.id);
  if (override === undefined) return msg;
  return { ...msg, expanded: override };
}

/**
 * Live Thought always shows the streaming body.
 * A finished Thought shows its body when expanded. The default is expanded
 * (see thinkingDisplay.ts). Do not treat done===true as "hide the body".
 * 废弃代码（2026-09-22）：expanded 默认 false，思考一结束这里返回 false，
 * 首位 Thought 正文被收掉。
 */
export function thoughtShowsBody(msg: { expanded?: boolean; done?: boolean }): boolean {
  return Boolean(msg.expanded) || msg.done !== true;
}
