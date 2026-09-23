/** Strip TUI chrome so clipboard gets the words the user typed, not █ / ─. */

const FRAME_ONLY = /^[\s█▌▐│┃┌┐└┘├┤┬┴┼─━═\-]+$/;
const LEADING_BAR = /^[\s]*[█▌│┃]\s?/;

export function sanitizeCopiedText(raw: string): string {
  return raw
    .split(/\r?\n/)
    .map((line) => line.replace(LEADING_BAR, "").replace(/[─━═]{8,}/g, "").trimEnd())
    .filter((line) => line.trim() !== "" && !FRAME_ONLY.test(line))
    .join("\n")
    .trim();
}
