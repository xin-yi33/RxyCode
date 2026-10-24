/**
 * Display-column helpers for the OpenTUI char-cell grid.
 *
 * Terminals lay text out in cells, not UTF-16 code units: CJK / fullwidth /
 * emoji graphemes occupy 2 cells. Numeric fields (durations, sizes, counts,
 * quotas) change width as values grow, so adjacent labels jitter unless each
 * numeric cell is padded by DISPLAY width, not string.length.
 *
 * All helpers are pure and shared by the status bar, tool cards, todo dock,
 * composer and file-name truncation.
 */
import { stringWidth } from "../layout.ts";

/** Display width in terminal cells (Bun.stringWidth when available: grapheme-correct). */
export function displayWidth(text: string): number {
  const bun = (globalThis as {
    Bun?: { stringWidth?: (value: string) => number };
  }).Bun;
  if (bun && typeof bun.stringWidth === "function") {
    try {
      return bun.stringWidth(text);
    } catch {
      // Fall through to the portable CJK table.
    }
  }
  return stringWidth(text);
}

/** Pad on the right until the cell width is reached (never truncates). */
export function padDisplayEnd(text: string, width: number): string {
  const target = Math.max(0, Math.trunc(width));
  const used = displayWidth(text);
  return used >= target ? text : text + " ".repeat(target - used);
}

/** Pad on the left until the cell width is reached (never truncates). */
export function padDisplayStart(text: string, width: number): string {
  const target = Math.max(0, Math.trunc(width));
  const used = displayWidth(text);
  return used >= target ? text : " ".repeat(target - used) + text;
}

/** Hard truncate to a cell budget; appends the ellipsis inside the budget. */
export function truncateDisplayEnd(text: string, width: number, ellipsis = "…"): string {
  const target = Math.max(0, Math.trunc(width));
  if (target <= 0 || !text) return "";
  if (displayWidth(text) <= target) return text;
  const ell = ellipsis && displayWidth(ellipsis) <= target ? ellipsis : "";
  const budget = target - displayWidth(ell);
  let out = "";
  let used = 0;
  for (const ch of text) {
    const cells = displayWidth(ch);
    if (used + cells > budget) break;
    out += ch;
    used += cells;
  }
  return out + ell;
}

/** Fit text into a cell budget (returns it unchanged when it already fits). */
export function fitDisplay(text: string, width: number): string {
  return displayWidth(text) <= Math.max(0, Math.trunc(width))
    ? text
    : truncateDisplayEnd(text, width);
}

/** Pad a column of cells to the widest cell (display width). */
export function alignCells(
  cells: readonly string[],
  align: "start" | "end" = "end",
): string[] {
  const width = Math.max(0, ...cells.map((cell) => displayWidth(cell)));
  return cells.map((cell) =>
    align === "end" ? padDisplayStart(cell, width) : padDisplayEnd(cell, width),
  );
}

/** Align both cells of a numeric pair (used/max quota, +added/-removed). */
export function alignPair(left: string, right: string): [string, string] {
  const width = Math.max(displayWidth(left), displayWidth(right));
  return [padDisplayStart(left, width), padDisplayStart(right, width)];
}

/** Numeric cell inside a fixed column. */
export function numericCell(value: string, width: number): string {
  return padDisplayStart(value, width);
}

/**
 * One-line row with a left context and a right status: pads between them with
 * display cells so the right edge stays put on resize. Shrinks the left side
 * first — the right side carries the actionable state.
 */
export function alignEdges(
  left: string,
  right: string,
  width: number,
  options: { shrink?: "left" | "right" } = {},
): { left: string; right: string; pad: number; fits: boolean } {
  const total = Math.max(0, Math.trunc(width));
  const leftWidth = displayWidth(left);
  const rightWidth = displayWidth(right);
  if (leftWidth + rightWidth <= total) {
    return { left, right, pad: total - leftWidth - rightWidth, fits: true };
  }
  if (options.shrink === "right") {
    // Keep the left context (attachments) and truncate the right notice.
    const fittedLeft = fitDisplay(left, total);
    const leftCells = displayWidth(fittedLeft);
    const fittedRight = truncateDisplayEnd(right, Math.max(0, total - leftCells));
    const rightCells = displayWidth(fittedRight);
    return {
      left: fittedLeft,
      right: fittedRight,
      pad: Math.max(0, total - leftCells - rightCells),
      fits: false,
    };
  }
  const fittedRight = truncateDisplayEnd(right, total);
  const rightCells = displayWidth(fittedRight);
  const fittedLeft = truncateDisplayEnd(left, Math.max(0, total - rightCells));
  const leftCells = displayWidth(fittedLeft);
  return {
    left: fittedLeft,
    right: fittedRight,
    pad: Math.max(0, total - leftCells - rightCells),
    fits: false,
  };
}

/* ── Numeric cell formatters (fixed-width friendly) ───────────────────── */

/** Column width that fits "59.9s", "1m05s", "12h03m". */
export const DURATION_COLUMN_WIDTH = 6;

/** Compact, locale-free duration for a numeric column. */
export function formatDurationCompact(elapsedMs: number): string {
  if (!Number.isFinite(elapsedMs) || elapsedMs < 0) return "0.0s";
  const ms = Math.max(0, Math.round(elapsedMs));
  if (ms < 60_000) {
    // 0.0s .. 59.9s — one decimal keeps the digit column stable at 5 cells.
    return `${(ms / 1000).toFixed(1)}s`;
  }
  const totalSec = Math.floor(ms / 1000);
  if (totalSec < 3600) {
    const minutes = Math.floor(totalSec / 60);
    const seconds = totalSec % 60;
    return `${minutes}m${String(seconds).padStart(2, "0")}s`;
  }
  const hours = Math.floor(totalSec / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  return `${hours}h${String(minutes).padStart(2, "0")}m`;
}

/** Right-aligned duration cell (durations end on the same grid column). */
export function durationCell(elapsedMs: number, width = DURATION_COLUMN_WIDTH): string {
  return numericCell(formatDurationCompact(elapsedMs), width);
}

const SIZE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"] as const;

/** Compact byte size ("0B", "12KB", "907KB", "1.2GB"). */
export function formatBytesCompact(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0B";
  let value = Math.floor(bytes);
  let unit = 0;
  while (value >= 1024 && unit < SIZE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  if (unit === 0) return `${Math.round(value)}B`;
  const rounded = value >= 100 ? value.toFixed(0) : value.toFixed(1);
  return `${rounded}${SIZE_UNITS[unit]}`;
}

/** Column width that fits "907.0k" / "12KB" / "1.2GB". */
export const SIZE_COLUMN_WIDTH = 6;

/** Right-aligned size cell. Accepts already-formatted server labels ("907.0k"). */
export function sizeCell(sizeLabel: string, width = SIZE_COLUMN_WIDTH): string {
  return numericCell(String(sizeLabel ?? "").trim() || "0B", width);
}

/** Column width for percentages ("33.0%", "100.0%"). */
export const RATE_COLUMN_WIDTH = 5;

/** Right-aligned percentage cell. */
export function rateCell(rateLabel: string, width = RATE_COLUMN_WIDTH): string {
  return numericCell(String(rateLabel ?? "").trim() || "0.0%", width);
}

export const QUOTA_USED_COLUMN_WIDTH = 5;
export const QUOTA_MAX_COLUMN_WIDTH = 5;

/** `used/max` quota with both sides right-aligned (slash column stays put). */
export function formatQuotaPair(
  usedLabel: string,
  maxLabel: string,
  usedWidth = QUOTA_USED_COLUMN_WIDTH,
  maxWidth = QUOTA_MAX_COLUMN_WIDTH,
): string {
  return `${numericCell(usedLabel, usedWidth)}/${numericCell(maxLabel, maxWidth)}`;
}

/** Split a `used/max` budget label; pads both sides so the slash aligns. */
export function formatBudgetPair(label: string): string {
  const [used = "", max = ""] = String(label ?? "").split("/");
  const [paddedUsed, paddedMax] = alignPair(used, max);
  return `${paddedUsed}/${paddedMax}`;
}

/** Count summary with the numeric column aligned ("2 completed, 1 cancelled"). */
export function formatCountSummary(
  items: ReadonlyArray<{ count: number; label: string }>,
): string {
  const rows = items.filter((item) => Number.isFinite(item.count) && item.count > 0);
  if (!rows.length) return "";
  const labels = rows.map((item) => String(Math.max(0, Math.trunc(item.count))));
  const width = Math.max(...labels.map((label) => displayWidth(label)));
  return rows
    .map((item, index) => `${padDisplayStart(labels[index]!, width)} ${item.label}`)
    .join(", ");
}

/** Signed diff counters with the digits on one grid column ("+ 3" / "-12"). */
export function alignSignedCounts(
  added: number,
  removed: number,
): { added: string; removed: string } {
  const addedLabel = String(Math.max(0, Math.trunc(Number.isFinite(added) ? added : 0)));
  const removedLabel = String(Math.max(0, Math.trunc(Number.isFinite(removed) ? removed : 0)));
  const width = Math.max(displayWidth(addedLabel), displayWidth(removedLabel));
  return {
    added: `+${padDisplayStart(addedLabel, width)}`,
    removed: `-${padDisplayStart(removedLabel, width)}`,
  };
}
