import stringWidth from 'string-width';

/**
 * Classic Unicode FULL BLOCK wordmark — R X Y C O D E.
 * Match reference screenshot: fg ink only on #000000 field (no cell bg fill).
 */
export const WORDMARK = [
  '███████  ██   ██  ██   ██   █████    █████   ██████    █████ ',
  '██   ██  ██   ██  ██   ██  ██   ██  ██   ██  ██   ██  ██   ██',
  '██   ██   ██ ██   ██   ██  ██       ██   ██  ██   ██  ███████',
  '███████    ███     ██ ██   ██       ██   ██  ██   ██  ██   ██',
  '██   ██   ██ ██     ███    ██       ██   ██  ██   ██  ██     ',
  '██   ██  ██   ██    ███    ██   ██  ██   ██  ██   ██  ██   ██',
  '██   ██  ██   ██    ███     █████    █████   ██████    █████ ',
] as const;

export const WORDMARK_UNICODE = WORDMARK;

export const LOGO_INK_TOP = '#FFB6C1';
export const LOGO_INK_BODY = '#FF69B4';
export const LOGO_FIELD_BG = '#000000';

export function logoInkForRow(rowIndex: number): string {
  return rowIndex === 0 ? LOGO_INK_TOP : LOGO_INK_BODY;
}

export function getWordmark(): readonly string[] {
  return WORDMARK;
}

export function getWordmarkDisplayWidth(lines: readonly string[] = WORDMARK): number {
  return Math.max(...lines.map((line) => stringWidth(line.replace(/ +$/, ''))));
}

export const WORDMARK_DISPLAY_WIDTH = getWordmarkDisplayWidth(WORDMARK);

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

export function renderWordmarkFrame(cols: number): string[] {
  const lines = getWordmark();
  const dw = getWordmarkDisplayWidth(lines);
  const leading = Math.max(0, Math.floor((cols - dw) / 2));
  const pad = ' '.repeat(leading);
  return lines.map((line) => pad + padToDisplayWidth(line.replace(/ +$/, ''), dw));
}
