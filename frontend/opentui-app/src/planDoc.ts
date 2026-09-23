export type PlanDoc = {
  title: string;
  body: string;
};

/** Grok-style: a plan preview is a markdown document, not a chat greeting. */
export function looksLikePlanDocument(text: string): boolean {
  const src = (text || "").trim();
  if (!src) return false;
  return /^#{1,3}\s+\S/m.test(src);
}

export function parsePlanDoc(text: string, steps?: string[]): PlanDoc {
  const raw = (text || "").trim() || (steps || []).join("\n").trim();
  const lines = raw.split(/\r?\n/);
  const heading = lines.find((line) => /^#{1,3}\s+\S/.test(line));
  const title = heading
    ? heading.replace(/^#{1,3}\s+/, "").trim().slice(0, 48)
    : "Plan";
  return { title: title || "Plan", body: raw || "（空计划）" };
}

export function planViewportLines(termRows: number, takeover = false): number {
  const rows = termRows > 0 ? termRows : 24;
  if (takeover) {
    // Header + composer + status ≈ 12 rows; the rest is the plan pager.
    return Math.max(8, rows - 12);
  }
  // Nested file view: leave the chat transcript visible (Grok-style).
  const budget = Math.max(10, Math.floor(rows * 0.42));
  return Math.min(18, Math.max(10, budget));
}

export function clampPlanScroll(scroll: number, lineCount: number, viewport: number): number {
  const max = Math.max(0, lineCount - Math.max(1, viewport));
  if (!Number.isFinite(scroll)) return 0;
  return Math.min(max, Math.max(0, Math.trunc(scroll)));
}
