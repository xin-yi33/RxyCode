/** Chat-message markdown rendering. Default on; /markdown and Settings flip it. */

let composerMarkdown = true;

export function composerMarkdownEnabled(): boolean {
  return composerMarkdown;
}

export function setComposerMarkdown(enabled: boolean): void {
  composerMarkdown = enabled;
}

export function cycleComposerMarkdown(): { enabled: boolean } {
  composerMarkdown = !composerMarkdown;
  return { enabled: composerMarkdown };
}

export function resetComposerMarkdown(): void {
  composerMarkdown = true;
}

export function applyComposerMarkdownArg(arg: string): { enabled: boolean } {
  const token = arg.trim().toLowerCase();
  if (token === "on" || token === "1" || token === "true") composerMarkdown = true;
  else if (token === "off" || token === "0" || token === "false") composerMarkdown = false;
  else composerMarkdown = !composerMarkdown;
  return { enabled: composerMarkdown };
}
