import stringWidth from 'string-width';

// RxyCode wordmark — R X Y C O D E (7x7 block letters, 2-space gap)
// Note: 6th letter must be D (not H — H has a mid crossbar).
export const WORDMARK = [
  '███████  ██   ██  ██   ██   █████    █████   ██████    █████ ',
  '██   ██  ██   ██  ██   ██  ██   ██  ██   ██  ██   ██  ██   ██',
  '██   ██   ██ ██   ██   ██  ██       ██   ██  ██   ██  ███████',
  '███████    ███     ██ ██   ██       ██   ██  ██   ██  ██   ██',
  '██   ██   ██ ██     ███    ██       ██   ██  ██   ██  ██     ',
  '██   ██  ██   ██    ███    ██   ██  ██   ██  ██   ██  ██   ██',
  '██   ██  ██   ██    ███     █████    █████   ██████    █████ ',
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
