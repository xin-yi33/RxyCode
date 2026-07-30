/** Pure grouping helpers (kept separate for unit tests without React). */
import { AVAILABLE_COMMANDS, type Command } from "./commands.ts";

export type DisplayRow =
  | { kind: "header"; category: string; key: string }
  | { kind: "item"; cmd: Command; flatIndex: number; key: string }
  | { kind: "empty"; key: string };

export const CATEGORY_ORDER = ["会话", "Agent", "记忆", "Skills", "MCP", "系统", "其他"];

function scoreCommand(cmd: Command, q: string): number {
  if (!q || q === "/") return 1;
  const needle = q.startsWith("/") ? q : `/${q}`;
  const name = cmd.name.toLowerCase();
  const blob = `${cmd.name} ${cmd.description} ${cmd.keywords ?? ""} ${cmd.category ?? ""}`.toLowerCase();
  if (name.startsWith(needle)) return 3;
  if (name.includes(needle) || blob.includes(q.replace(/^\//, ""))) return 2;
  return 0;
}

export function filterAndGroup(query: string): { flat: Command[]; rows: DisplayRow[] } {
  const q = query.trim().toLowerCase();
  const scored = AVAILABLE_COMMANDS.map((cmd) => ({
    cmd,
    score: scoreCommand(cmd, q),
  })).filter((x) => x.score > 0);

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    const ca = CATEGORY_ORDER.indexOf(a.cmd.category || "其他");
    const cb = CATEGORY_ORDER.indexOf(b.cmd.category || "其他");
    if (ca !== cb) return (ca < 0 ? 99 : ca) - (cb < 0 ? 99 : cb);
    return a.cmd.name.localeCompare(b.cmd.name);
  });

  const flat = scored.map((x) => x.cmd);
  const rows: DisplayRow[] = [];

  if (q && q !== "/") {
    flat.forEach((cmd, flatIndex) => {
      rows.push({ kind: "item", cmd, flatIndex, key: `i-${cmd.name}` });
    });
    return { flat, rows };
  }

  const groups = new Map<string, Command[]>();
  for (const cmd of flat) {
    const cat = cmd.category || "其他";
    if (!groups.has(cat)) groups.set(cat, []);
    groups.get(cat)!.push(cmd);
  }

  let flatIndex = 0;
  for (const cat of CATEGORY_ORDER) {
    const items = groups.get(cat);
    if (!items?.length) continue;
    rows.push({ kind: "header", category: cat, key: `h-${cat}` });
    for (const cmd of items) {
      rows.push({ kind: "item", cmd, flatIndex, key: `i-${cmd.name}` });
      flatIndex += 1;
    }
  }
  for (const [cat, items] of groups) {
    if (CATEGORY_ORDER.includes(cat)) continue;
    rows.push({ kind: "header", category: cat, key: `h-${cat}` });
    for (const cmd of items) {
      rows.push({ kind: "item", cmd, flatIndex, key: `i-${cmd.name}` });
      flatIndex += 1;
    }
  }
  return { flat, rows };
}
