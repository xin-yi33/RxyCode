/** Terminal layout helpers for OpenTUI (Ink-parity geometry). */

/** Display width: CJK / fullwidth count as 2. */
export function stringWidth(text: string): number {
  let w = 0;
  for (const ch of text) {
    const cp = ch.codePointAt(0) ?? 0;
    if (
      cp >= 0x1100 &&
      (cp <= 0x115f ||
        cp === 0x2329 ||
        cp === 0x232a ||
        (cp >= 0x2e80 && cp <= 0xa4cf && cp !== 0x303f) ||
        (cp >= 0xac00 && cp <= 0xd7a3) ||
        (cp >= 0xf900 && cp <= 0xfaff) ||
        (cp >= 0xfe10 && cp <= 0xfe19) ||
        (cp >= 0xfe30 && cp <= 0xfe6f) ||
        (cp >= 0xff00 && cp <= 0xff60) ||
        (cp >= 0xffe0 && cp <= 0xffe6) ||
        (cp >= 0x20000 && cp <= 0x2fffd) ||
        (cp >= 0x30000 && cp <= 0x3fffd))
    ) {
      w += 2;
    } else {
      w += 1;
    }
  }
  return w;
}

/** Number of wrapped visual lines for `text` given inner wrap width. */
export function numInputLines(text: string, wrapW: number): number {
  const w = Math.max(1, wrapW);
  return text
    .split("\n")
    .reduce((total, line) => total + Math.max(1, Math.ceil(stringWidth(line) / w)), 0);
}

/** Soft-wrap a single logical line into display chunks of at most wrapW. */
export function wrapLine(line: string, wrapW: number): string[] {
  const w = Math.max(1, wrapW);
  if (!line) return [""];
  if (stringWidth(line) <= w) return [line];
  const out: string[] = [];
  let buf = "";
  let bufW = 0;
  for (const ch of line) {
    const cw = stringWidth(ch);
    if (bufW + cw > w && buf) {
      out.push(buf);
      buf = ch;
      bufW = cw;
    } else {
      buf += ch;
      bufW += cw;
    }
  }
  if (buf) out.push(buf);
  return out.length ? out : [""];
}

/** Split content into display lines (hard newlines + soft wrap). */
export function wrapContentLines(content: string, wrapW: number): string[] {
  const logical = content.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const out: string[] = [];
  for (const line of logical) {
    out.push(...wrapLine(line, wrapW));
  }
  return out.length ? out : [""];
}

export const INPUT_MAX_VISIBLE_LINES = 10;
export const INPUT_MIN_VISIBLE_LINES = 1;

/** Visible textarea height: grows with content, capped for scrolling. */
export function inputVisibleLines(text: string, wrapW: number): number {
  const n = numInputLines(text || "", wrapW);
  return Math.max(
    INPUT_MIN_VISIBLE_LINES,
    Math.min(INPUT_MAX_VISIBLE_LINES, n),
  );
}

export function needsInputScroll(text: string, wrapW: number): boolean {
  return numInputLines(text || "", wrapW) > INPUT_MAX_VISIBLE_LINES;
}
