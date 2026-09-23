/** Parse tool args and classify Grok-Build-style tool cards. */

export type ToolFamily = "edit" | "read" | "bash" | "generic";

export type DiffLine = { kind: "add" | "del" | "ctx"; text: string };

const EDIT_TOOLS = new Set([
  "write",
  "write_file",
  "edit",
  "edit_file",
  "create_file",
  "str_replace",
  "patch",
  "apply_patch",
]);

const READ_TOOLS = new Set(["read", "view", "open_file", "grep"]);

const BASH_TOOLS = new Set(["bash", "shell"]);

/** Internal steps. Codex/Grok do not surface these as chat cards.
 *  ``final_answer`` is the turn-exit signal; its text is already the reply.
 *  废弃代码（2026-09-22）：return key === "history" 会把 final_answer 画成工具卡。
 */
export function shouldHideToolCard(name: string | undefined, _content?: string): boolean {
  const key = (name || "").trim().toLowerCase().replace(/-/g, "_");
  return key === "history" || key === "final_answer";
}

export function classifyTool(name: string | undefined): ToolFamily {
  const key = (name || "tool").trim().toLowerCase();
  if (EDIT_TOOLS.has(key)) return "edit";
  if (READ_TOOLS.has(key)) return "read";
  if (BASH_TOOLS.has(key)) return "bash";
  return "generic";
}

export function serializeToolArgs(args: string | Record<string, unknown> | undefined): string {
  if (args == null) return "";
  if (typeof args === "string") return args;
  try {
    return JSON.stringify(args);
  } catch {
    return "";
  }
}

export function parseToolArgs(
  raw: string | Record<string, unknown> | undefined,
): Record<string, unknown> {
  if (raw == null) return {};
  if (typeof raw === "object") return raw;
  const trimmed = raw.trim();
  if (!trimmed) return {};
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
    } catch {
      return { _raw: raw, command: raw };
    }
  }
  return { _raw: raw, command: raw };
}

export function argStr(obj: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = obj[key];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return "";
}

export function isPlanMdPath(path: string): boolean {
  return /(^|[\\/])plan\.md$/i.test(path || "");
}

export function fileLabel(path: string): string {
  if (!path) return "";
  const normalized = path.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length >= 2 && isPlanMdPath(parts[parts.length - 1] || "")) {
    return parts.slice(-3).join("/");
  }
  return parts[parts.length - 1] || path;
}

export function toolPath(args: Record<string, unknown>): string {
  return argStr(args, "filePath", "file_path", "path", "target");
}

export function toolCommand(args: Record<string, unknown>): string {
  return argStr(args, "command", "cmd", "_raw", "raw");
}

export function lineDiff(oldText: string, newText: string): DiffLine[] {
  const a = oldText.split("\n");
  const b = newText.split("\n");
  if (a.length * b.length > 80_000) {
    return [
      ...a.map((text) => ({ kind: "del" as const, text })),
      ...b.map((text) => ({ kind: "add" as const, text })),
    ];
  }
  const n = a.length;
  const m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ kind: "ctx", text: a[i] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ kind: "del", text: a[i] });
      i += 1;
    } else {
      out.push({ kind: "add", text: b[j] });
      j += 1;
    }
  }
  while (i < n) {
    out.push({ kind: "del", text: a[i] });
    i += 1;
  }
  while (j < m) {
    out.push({ kind: "add", text: b[j] });
    j += 1;
  }
  return out;
}

export function parseUnifiedDiff(diff: string): DiffLine[] {
  const out: DiffLine[] = [];
  for (const line of diff.split("\n")) {
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@") || line.startsWith("diff ")) {
      continue;
    }
    if (line.startsWith("+")) out.push({ kind: "add", text: line.slice(1) });
    else if (line.startsWith("-")) out.push({ kind: "del", text: line.slice(1) });
    else if (line.startsWith(" ")) out.push({ kind: "ctx", text: line.slice(1) });
  }
  return out;
}

export function buildEditDiff(name: string | undefined, args: Record<string, unknown>): DiffLine[] {
  const key = (name || "").toLowerCase();
  const patch = argStr(args, "diff", "patch");
  if (patch) return parseUnifiedDiff(patch);
  const oldText = argStr(args, "oldString", "old_string", "old");
  const newText = argStr(args, "newString", "new_string", "new");
  if (oldText || newText) return lineDiff(oldText, newText);
  const written = argStr(args, "content", "contents");
  if (written && (key.includes("write") || key.includes("create"))) {
    return written.split("\n").map((text) => ({ kind: "add" as const, text }));
  }
  return [];
}

export function groupDiffHunks(
  lines: DiffLine[],
): Array<{ kind: DiffLine["kind"]; lines: DiffLine[] }> {
  const groups: Array<{ kind: DiffLine["kind"]; lines: DiffLine[] }> = [];
  for (const line of lines) {
    const last = groups[groups.length - 1];
    if (last && last.kind === line.kind) last.lines.push(line);
    else groups.push({ kind: line.kind, lines: [line] });
  }
  return groups;
}

/** Grok-style hunk: only +/- lines, first `max` of them. Counts stay full. */
export function selectLinePreview(
  lines: string[],
  max = 6,
): { lines: string[]; clipped: number } {
  if (lines.length <= max) return { lines, clipped: 0 };
  return { lines: lines.slice(0, max), clipped: lines.length - max };
}

export function selectDiffPreview(
  lines: DiffLine[],
  max = 12,
): { lines: DiffLine[]; clipped: number } {
  const changes = lines.filter((line) => line.kind !== "ctx");
  if (changes.length <= max) return { lines: changes, clipped: 0 };
  return { lines: changes.slice(0, max), clipped: changes.length - max };
}

export function diffCounts(lines: DiffLine[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const line of lines) {
    if (line.kind === "add") added += 1;
    if (line.kind === "del") removed += 1;
  }
  return { added, removed };
}

export function grepReadTargets(args: Record<string, unknown>, result: string): string[] {
  const files = new Set<string>();
  for (const line of (result || "").split("\n")) {
    const match = line.match(/^(.+?)[:：](\d+)[:：]/);
    if (match?.[1]) files.add(match[1]);
  }
  if (files.size === 0) {
    const argPath = toolPath(args);
    if (argPath) files.add(argPath);
  }
  if (files.size === 0) {
    const pattern = argStr(args, "pattern", "query", "include");
    if (pattern) files.add(pattern);
  }
  return [...files];
}

export function readTargets(
  name: string | undefined,
  args: Record<string, unknown>,
  result: string,
): string[] {
  const key = (name || "").toLowerCase();
  if (key === "grep") return grepReadTargets(args, result);
  const path = toolPath(args);
  return path ? [path] : [];
}

export function genericSummary(name: string | undefined, args: Record<string, unknown>): string {
  const key = (name || "tool").toLowerCase();
  if (key === "glob") {
    const pattern = argStr(args, "pattern");
    const path = toolPath(args);
    return path ? `glob: ${pattern} in ${path}` : `glob: ${pattern || ""}`;
  }
  if (key === "websearch" || key === "search") {
    return `search: ${argStr(args, "query", "q", "pattern", "command")}`;
  }
  if (key === "webfetch" || key === "fetch") {
    return `fetch: ${argStr(args, "url", "href", "command")}`;
  }
  if (key === "ls") {
    return `ls: ${toolPath(args) || "."}`;
  }
  if (key === "skill") {
    return `skill: ${argStr(args, "name", "skill", "command")}`;
  }
  if (key === "git") {
    return `git: ${argStr(args, "command", "args", "_raw")}`;
  }
  if (key === "datetime") {
    return "datetime";
  }
  const path = toolPath(args);
  if (path) return `${key}: ${path}`;
  const command = toolCommand(args);
  if (command && command !== JSON.stringify(args)) return command;
  return "";
}
