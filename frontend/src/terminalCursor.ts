export interface TerminalWriter {
  isTTY?: boolean;
  write(chunk: string): unknown;
}

const SHOW_CURSOR = '\x1b[?25h';
const HIDE_CURSOR = '\x1b[?25l';
const ENABLE_BLINK = '\x1b[?12h';
const DISABLE_BLINK = '\x1b[?12l';

export function initializeTerminalCursor(out: TerminalWriter): void {
  if (!out.isTTY) return;
  out.write(ENABLE_BLINK + SHOW_CURSOR);
}

export function positionTerminalCursor(out: TerminalWriter, row: number, column: number): void {
  if (!out.isTTY) return;
  const safeRow = Math.max(1, Math.floor(row));
  const safeColumn = Math.max(1, Math.floor(column));
  out.write(`${SHOW_CURSOR}\x1b[${safeRow};${safeColumn}H`);
}

export function hideTerminalCursor(out: TerminalWriter): void {
  if (out.isTTY) out.write(HIDE_CURSOR);
}

// --- Frame-synchronized cursor anchor (问题1/2 根修) -------------------------
//
// Paradigm adapted from google-gemini/gemini-cli (Apache-2.0): the cursor must
// be an artifact of the RENDERED FRAME, never of a timer racing against Ink's
// own stdout writes. gemini-cli achieves this by drawing an inverse-video
// cursor inside the Ink tree; RxyCode intentionally keeps the terminal's
// native thin blinking caret, so we get the same race-free property by
// re-asserting the cursor position synchronously AFTER EVERY stdout write:
//
//   1. Ink (log-update) writes a frame that always ends with "\n", leaving the
//      real cursor on the line just below the StatusBar (the frame's last line).
//   2. We save that position (DECSC), move the cursor UP a known number of
//      rows — pure frame-relative math, valid whether or not the frame fills
//      the screen — set the column, and show the caret.
//   3. Before the NEXT write we restore (DECRC) so log-update's line-erasure
//      math is never corrupted by our movement.
//
// This replaces the old `setTimeout(0)` absolute-row positioning, which lost
// every race against frames triggered by OTHER components (spinner ticks,
// status polls) and left the caret at the end of the frame — right after the
// StatusBar "设置" text (问题1) — or one row too high from the off-by-one
// absolute math (问题2).

export interface CursorAnchor {
  /** rows to move UP from the frame-end line (line below the StatusBar). */
  rowsUp: number;
  /** 1-based terminal column of the caret. */
  column: number;
}

const SAVE_CURSOR = '\x1b7';
const RESTORE_CURSOR = '\x1b8';

let anchor: CursorAnchor | null = null;
let needsRestore = false;
let installedOn: (TerminalWriter & { write: (...args: unknown[]) => unknown }) | null = null;
let originalWrite: ((...args: unknown[]) => unknown) | null = null;

function assertAnchor(write: (chunk: string) => unknown): void {
  if (needsRestore) {
    write(RESTORE_CURSOR);
    needsRestore = false;
  }
  if (anchor) {
    const up = Math.max(0, Math.floor(anchor.rowsUp));
    const col = Math.max(1, Math.floor(anchor.column));
    write(`${SAVE_CURSOR}${up > 0 ? `\x1b[${up}A` : ''}\x1b[${col}G${SHOW_CURSOR}`);
    needsRestore = true;
  } else {
    write(HIDE_CURSOR);
  }
}

/**
 * Wrap `out.write` so the caret is re-asserted after every frame Ink flushes.
 * Idempotent; no-op for non-TTY streams (tests, pipes).
 */
export function installCursorAnchor(out: TerminalWriter): void {
  if (!out.isTTY || installedOn) return;
  const target = out as TerminalWriter & { write: (...args: unknown[]) => unknown };
  const orig = target.write.bind(target);
  installedOn = target;
  originalWrite = orig;
  target.write = (...args: unknown[]) => {
    if (needsRestore) {
      orig(RESTORE_CURSOR);
      needsRestore = false;
    }
    const result = orig(...args);
    if (anchor) assertAnchor(orig as (chunk: string) => unknown);
    return result;
  };
}

/** Undo installCursorAnchor and hide the caret. */
export function uninstallCursorAnchor(): void {
  if (!installedOn || !originalWrite) return;
  if (needsRestore) {
    originalWrite(RESTORE_CURSOR);
    needsRestore = false;
  }
  originalWrite(HIDE_CURSOR);
  installedOn.write = originalWrite as never;
  installedOn = null;
  originalWrite = null;
  anchor = null;
}

/**
 * Update the caret anchor (or hide it with `null`) and apply it immediately.
 * Called from InputBox's layout effect — which runs AFTER Ink has written the
 * frame, so applying synchronously here is already race-free.
 */
export function setCursorAnchor(out: TerminalWriter, next: CursorAnchor | null): void {
  anchor = next;
  if (!out.isTTY) return;
  const write = (originalWrite ?? out.write.bind(out)) as (chunk: string) => unknown;
  assertAnchor(write);
}

export function restoreTerminalCursor(out: TerminalWriter): void {
  if (!out.isTTY) return;
  out.write(DISABLE_BLINK + SHOW_CURSOR);
}
