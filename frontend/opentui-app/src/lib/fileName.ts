/**
 * Long file names in a terminal, by display cells.
 *
 * Middle ellipsis keeps both the beginning and the extension.  A plain
 * end-truncation hides the suffix ("…docx"), so users cannot tell a .tar.gz
 * from a .txt.  Compound suffixes (.tar.gz / .tar.xz / .min.js / …) are
 * treated as one suffix and never split.
 */
import { displayWidth, truncateDisplayEnd } from "./displayColumns.ts";

export const COMPOUND_SUFFIXES = [
  ".tar.gz",
  ".tar.bz2",
  ".tar.xz",
  ".tar.zst",
  ".min.js",
  ".min.css",
  ".user.js",
  ".d.ts",
] as const;

/** Split "archive.tar.gz" into { stem: "archive", suffix: ".tar.gz" }. */
export function splitCompoundSuffix(name: string): { stem: string; suffix: string } {
  const raw = String(name ?? "");
  const lower = raw.toLowerCase();
  for (const suffix of COMPOUND_SUFFIXES) {
    if (lower.endsWith(suffix) && raw.length > suffix.length) {
      return { stem: raw.slice(0, -suffix.length), suffix: raw.slice(-suffix.length) };
    }
  }
  const dot = raw.lastIndexOf(".");
  // ".gitignore" / "Dockerfile" / "Makefile" have no meaningful suffix to keep.
  if (dot > 0 && dot < raw.length - 1) {
    return { stem: raw.slice(0, dot), suffix: raw.slice(dot) };
  }
  return { stem: raw, suffix: "" };
}

function takePrefix(text: string, budget: number): string {
  const target = Math.max(0, Math.trunc(budget));
  let out = "";
  let used = 0;
  for (const ch of text) {
    const cells = displayWidth(ch);
    if (used + cells > target) break;
    out += ch;
    used += cells;
  }
  return out;
}

function takeSuffix(text: string, budget: number): string {
  const target = Math.max(0, Math.trunc(budget));
  let out = "";
  let used = 0;
  for (const ch of Array.from(text).reverse()) {
    const cells = displayWidth(ch);
    if (used + cells > target) break;
    out = ch + out;
    used += cells;
  }
  return out;
}

export interface SplitFileName {
  /** The rendered cell; fits within `maxWidth` cells. */
  text: string;
  /** Kept leading part of the stem. */
  head: string;
  /** Preserved trailing suffix ("" when the name had none). */
  suffix: string;
  /** True when the name had to be shortened. */
  truncated: boolean;
}

/**
 * Split a file name to `maxWidth` display cells with a middle ellipsis:
 * the extension (incl. compound suffixes such as .tar.gz) is preserved.
 */
export function splitFileNameForWidth(
  name: string,
  maxWidth: number,
  ellipsis = "…",
): SplitFileName {
  const raw = String(name ?? "");
  const width = Math.max(0, Math.trunc(Number.isFinite(maxWidth) ? maxWidth : 0));
  if (!raw) return { text: "", head: "", suffix: "", truncated: false };
  if (displayWidth(raw) <= width) {
    return { text: raw, head: raw, suffix: "", truncated: false };
  }
  if (width <= 0) return { text: "", head: "", suffix: "", truncated: true };

  const ell = displayWidth(ellipsis) < width ? ellipsis : "";
  const ellCells = displayWidth(ell);
  const { stem, suffix } = splitCompoundSuffix(raw);
  const suffixCells = displayWidth(suffix);

  // Preferred: keep the whole suffix and as much of the stem as budget allows.
  if (suffix && suffixCells + ellCells + 1 <= width) {
    const head = takePrefix(stem, width - ellCells - suffixCells);
    if (head) return { text: head + ell + suffix, head, suffix, truncated: true };
  }

  // Fallback: keep both ends (still mid-ellipsis) when the suffix alone is too wide.
  const tailBudget = Math.max(1, Math.min(displayWidth(suffix || raw), width - ellCells - 1));
  const tail = takeSuffix(suffix || raw, tailBudget);
  const headBudget = Math.max(0, width - ellCells - displayWidth(tail));
  const head = takePrefix(stem || raw, headBudget);
  const text = head || tail ? head + ell + tail : truncateDisplayEnd(raw, width);
  return { text, head, suffix: suffix || tail, truncated: true };
}

/** Convenience wrapper used by attachment / session / artifact lines. */
export function middleEllipsisFileName(name: string, maxWidth: number): string {
  return splitFileNameForWidth(name, maxWidth).text;
}
