import { describe, expect, test } from "bun:test";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import {
  applyTodoUpdated,
  keyAction,
  todoDockLines,
  todoMark,
  type TodoDockSnapshot,
} from "./todoDock.ts";

const OPEN: TodoDockSnapshot = {
  list_id: "default",
  revision: 1,
  items: [
    { id: "t1", content: "搭骨架", status: "in_progress" },
    { id: "t2", content: "装依赖", status: "pending" },
  ],
};

describe("U-F5-4 todo dock", () => {
  test("U-F5-4-01 loads two items then collapses when the event completes them", () => {
    const first = todoDockLines(OPEN);
    const text = first.join("\n");
    expect(text).toContain("[•]");
    expect(text).toContain("搭骨架");
    expect(text).toContain("[ ]");
    expect(text).toContain("装依赖");
    const next = applyTodoUpdated(OPEN, {
      event_id: "e1",
      seq: 2,
      timestamp: "2026-10-08T00:00:00Z",
      snapshot: {
        list_id: "default",
        revision: 2,
        items: [
          { id: "t1", content: "搭骨架", status: "completed" },
          { id: "t2", content: "装依赖", status: "completed" },
        ],
      },
    });
    expect(todoMark("completed")).toBe("[✓]");
    expect(todoDockLines(next)).toEqual([]);
  });

  test("U-F5-4-02 Ctrl+T toggles todo and Ctrl+E toggles thinking", () => {
    expect(keyAction({ ctrl: true, name: "t" })).toBe("todo");
    expect(keyAction({ ctrl: true, name: "e" })).toBe("thinking");
    expect(keyAction({ ctrl: true, name: "p" })).toBeNull();
    const leftover = grepSource(/Ctrl\+T.*思考|Ctrl\+T.*thinking/i);
    expect(leftover).toEqual([]);
  });

  test("U-F5-4-03 empty snapshot renders no rows", () => {
    const lines = todoDockLines({ list_id: "default", revision: 0, items: [] });
    expect(lines).toEqual([]);
    expect(lines.length).toBe(0);
  });
});

function grepSource(pattern: RegExp): string[] {
  const root = join(import.meta.dir);
  const hits: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      const info = statSync(path);
      if (info.isDirectory()) {
        if (name === "node_modules") continue;
        walk(path);
        continue;
      }
      if (!/\.(ts|tsx)$/.test(name) || name.endsWith(".test.ts") || name.endsWith(".test.tsx")) {
        continue;
      }
      const text = readFileSync(path, "utf8");
      text.split(/\r?\n/).forEach((line, index) => {
        if (pattern.test(line)) hits.push(`${path}:${index + 1}:${line.trim()}`);
      });
    }
  };
  walk(root);
  return hits;
}
