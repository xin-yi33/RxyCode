/** Per-card expand + long-result tail. Default is open; /tools and /settings flip the default. */

const expandedById = new Map<string, boolean>();
const fullResultById = new Map<string, boolean>();
let defaultExpanded = true;

export const TOOL_PREVIEW_LINES = 6;
export const EDIT_PREVIEW_LINES = 12;

export function previewLimitForFamily(family: string): number {
  return family === "edit" ? EDIT_PREVIEW_LINES : TOOL_PREVIEW_LINES;
}

export function toolCardsDefaultExpanded(): boolean {
  return defaultExpanded;
}

export function cycleToolCardsDefault(): { expanded: boolean } {
  defaultExpanded = !defaultExpanded;
  return { expanded: defaultExpanded };
}

export function setToolCardsDefault(expanded: boolean): void {
  defaultExpanded = expanded;
}

export function setToolExpandedOverride(id: string, expanded: boolean): void {
  expandedById.set(id, expanded);
}

export function toggleToolExpanded(id: string, current: boolean): boolean {
  const next = !current;
  expandedById.set(id, next);
  return next;
}

export function setToolFullResult(id: string, full: boolean): void {
  fullResultById.set(id, full);
}

export function toggleToolFullResult(id: string, current: boolean): boolean {
  const next = !current;
  fullResultById.set(id, next);
  return next;
}

export function getToolFullResult(id: string): boolean {
  return fullResultById.get(id) === true;
}

export function applyToolExpandedOverride<
  T extends { id: string; role: string; toolExpanded?: boolean },
>(msg: T): T {
  if (msg.role !== "tool") return msg;
  const override = expandedById.get(msg.id);
  if (override !== undefined) return { ...msg, toolExpanded: override };
  if (msg.toolExpanded === undefined) return { ...msg, toolExpanded: defaultExpanded };
  return msg;
}

export function resetToolCardDisplay(): void {
  expandedById.clear();
  fullResultById.clear();
  defaultExpanded = true;
}
