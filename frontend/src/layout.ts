import stringWidth from 'string-width';
import { graphemeSpans } from './grapheme.js';

/**
 * Shared terminal-layout helpers.
 *
 * The command palette and the generic Modal are bottom-anchored lists. To keep
 * mouse-coordinate math correct (mouseManager assumes the list is flush at the
 * bottom) AND to avoid overflow in short terminals, their height must adapt to
 * the available rows instead of being hardcoded.
 *
 *   - palette: border(1) + title(1) + search(1) + divider(1) + items + bottom(1)
 *   - modal:   border(1) + title(1) + divider(1) + items + bottom(1)
 */

const PALETTE_FIXED = 6; // border+title+search+divider+bottom (no items)
const MODAL_FIXED = 4; // border+title+divider+bottom (no items)
const ABSOLUTE_MAX = 12;
const ABSOLUTE_MIN = 4;

/** Number of visible item rows that fit, given the terminal height. */
export function maxVisibleFor(termRows: number): number {
  // Reserve: 1 (header) + 1 (status bar) + 1 (input min) + the fixed chrome.
  const available = termRows - 1 - 1 - 1 - PALETTE_FIXED;
  return Math.max(ABSOLUTE_MIN, Math.min(ABSOLUTE_MAX, available));
}

/** Total rendered rows of the command palette for the given terminal height. */
export function paletteHeight(termRows: number): number {
  return maxVisibleFor(termRows) + PALETTE_FIXED;
}

/** Total rendered rows of a modal showing `mv` visible items. */
export function modalHeight(mv: number): number {
  return mv + MODAL_FIXED;
}

// --- Input box geometry (shared by the native cursor AND click-to-cursor) ---
// The InputBox is always directly above the 1-row StatusBar. Its bordered box
// is exactly: top border(1) + header(1) + text lines(numTextLines) + bottom
// border(1) = numTextLines + 3 rows.
// Keeping this math in one place means the cursor (Bug 1) and the mouse
// click-to-cursor (Bug 4) can never disagree about where the input lives —
// the same approach opencode uses for its bottom input geometry.
export const INPUT_BOX_TOP_BORDER = 1;
export const INPUT_BOX_HEADER = 1;
export const STATUS_BAR_ROWS = 1;
export const INPUT_BOX_BOTTOM_BORDER = 1;

/**
 * 1-based SCREEN row of the input box's FIRST text line (the `> ` prompt line),
 * valid when the rendered frame fills the terminal (StatusBar on the last row).
 *
 * Derivation (bottom-anchored): StatusBar = termRows, bottom border =
 * termRows-1, last text line = termRows-2, first text line =
 * termRows - STATUS_BAR_ROWS - numTextLines. The previous formula returned one
 * row too high (off-by-one, 问题2) and wrongly shifted by `commandsAbove` —
 * the `/` command list renders ABOVE the bordered box, which stays pinned to
 * the bottom, so it never moves the text rows. The parameter is kept for call
 * compatibility but intentionally ignored.
 */
export function inputTextRow(
  termRows: number,
  numTextLines: number,
  _commandsAbove: number,
): number {
  return termRows - STATUS_BAR_ROWS - numTextLines;
}

/**
 * Rows to move UP from the frame-end line (the line just below the StatusBar,
 * where Ink's log-update leaves the real cursor after every frame) to reach
 * text line `lineIndex` (0-based). Frame-RELATIVE, so it stays correct even
 * when the frame is shorter than the terminal (session start) — the failure
 * mode of absolute-row math. Paradigm: gemini-cli renders its caret inside the
 * frame; this is the equivalent for a native caret.
 */
export function cursorRowsFromFrameEnd(numTextLines: number, lineIndex: number): number {
  const clamped = Math.max(0, Math.min(numTextLines - 1, lineIndex));
  return STATUS_BAR_ROWS + INPUT_BOX_BOTTOM_BORDER + (numTextLines - clamped);
}

/** Number of wrapped text lines for `text` given the inner wrap width. */
export function numInputLines(text: string, wrapW: number): number {
  const w = Math.max(1, wrapW);
  return text
    .split('\n')
    .reduce((total, line) => total + Math.max(1, Math.ceil(stringWidth(line) / w)), 0);
}

/** Zero-based visual row and display column of a UTF-16 caret offset. */
export function caretVisualPosition(
  text: string,
  offset: number,
  wrapW: number,
): { lineIndex: number; column: number } {
  const w = Math.max(1, wrapW);
  const beforeCaret = text.slice(0, Math.max(0, Math.min(text.length, offset)));
  const logicalLines = beforeCaret.split('\n');
  let lineIndex = 0;
  for (const line of logicalLines.slice(0, -1)) {
    lineIndex += Math.max(1, Math.ceil(stringWidth(line) / w));
  }
  const currentWidth = stringWidth(logicalLines[logicalLines.length - 1] ?? '');
  lineIndex += Math.floor(currentWidth / w);
  return { lineIndex, column: currentWidth % w };
}

/**
 * Reverse-map a mouse click (1-based `x`/`y` in SGR-1006 coords) to a caret
 * offset inside `input`. Returns the clamped offset, or `-1` when the click
 * lands outside the input text block (header, border, StatusBar, or the chat
 * area above). Used by InputBox's click-to-cursor (Bug 4) and is pure so it can
 * be unit-tested without a TTY — the same geometry `inputTextRow`/`numInputLines`
 * already provide.
 */
export function caretOffsetFromClick(
  x: number,
  y: number,
  input: string,
  termWidth: number,
  termRows: number,
  commandsAbove: number,
): number {
  const startCell = 4; // 0-based: first input char sits at column 5
  const wrapW = Math.max(10, termWidth - 6);
  const numTextLines = numInputLines(input, wrapW);
  const firstRow = inputTextRow(termRows, numTextLines, commandsAbove);
  const lineIndex = y - firstRow; // 0-based line within the text block
  if (lineIndex < 0 || lineIndex >= numTextLines) return -1; // outside text block
  if (x < startCell + 1) return -1; // left of the `> ` prompt
  let rowStart = 0;
  let logicalOffset = 0;
  const logicalLines = input.split('\n');
  for (let logicalIndex = 0; logicalIndex < logicalLines.length; logicalIndex += 1) {
    const logicalLine = logicalLines[logicalIndex];
    const visualRows = Math.max(1, Math.ceil(stringWidth(logicalLine) / wrapW));
    if (lineIndex >= rowStart && lineIndex < rowStart + visualRows) {
      const wrappedLineIndex = lineIndex - rowStart;
      const colBefore = (x - 1) - startCell + wrappedLineIndex * wrapW;
      let best = 0;
      let bestDiff = Math.abs(colBefore);
      let acc = 0;
      for (const span of graphemeSpans(logicalLine)) {
        const nextAcc = acc + stringWidth(span.segment);
        const nextDiff = Math.abs(nextAcc - colBefore);
        if (nextDiff < bestDiff) {
          bestDiff = nextDiff;
          best = span.end;
        }
        acc = nextAcc;
      }
      return logicalOffset + best;
    }
    rowStart += visualRows;
    logicalOffset += logicalLine.length + (logicalIndex < logicalLines.length - 1 ? 1 : 0);
  }
  return -1;
}
