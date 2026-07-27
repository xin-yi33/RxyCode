import stringWidth from 'string-width';

// RxyCode wordmark — unified 7x7 block letters
// All letters exactly 7 rows × 7 cols, 2-space gap
// 'e' row 3 adjusted to fill right edge
// All lines ljust'd to 61 chars
export const WORDMARK = [
  '███████  ██   ██  ██   ██   █████    █████   ██   ██   █████ ',
  '██   ██  ██   ██  ██   ██  ██   ██  ██   ██  ██   ██  ██   ██',
  '██   ██   ██ ██   ██   ██  ██       ██   ██  ███████  ███████',
  '███████    ███     ██ ██   ██       ██   ██  ██   ██  ██   ██',
  '██   ██   ██ ██     ███    ██       ██   ██  ██   ██  ██     ',
  '██   ██  ██   ██    ███    ██   ██  ██   ██  ██   ██  ██   ██',
  '██   ██  ██   ██    ███     █████    █████   ██   ██   █████ ',
] as const;

/** Max display width of wordmark lines after trimming trailing spaces. */
export const WORDMARK_DISPLAY_WIDTH = Math.max(
  ...WORDMARK.map((line) => stringWidth(line.replace(/ +$/, ''))),
);

export function padToDisplayWidth(line: string, targetWidth: number): string {
  const w = stringWidth(line);
  if (w >= targetWidth) return line;
  return line + ' '.repeat(targetWidth - w);
}

export function centerLine(line: string, width: number): string {
  const lineWidth = stringWidth(line);
  if (width <= lineWidth) return line;
  const pad = Math.max(0, Math.floor((width - lineWidth) / 2));
  return ' '.repeat(pad) + line;
}
