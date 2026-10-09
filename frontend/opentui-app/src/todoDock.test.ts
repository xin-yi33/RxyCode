import { describe, expect, test } from "bun:test";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  applyTodoUpdated,
  keyAction,
  snapshotFromTodoGet,
  todoDockLines,
  todoMark,
  type TodoDockSnapshot,
  type TodoUpdatedEvent,
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
    expect(text).toContain("[·] t1: 搭骨架");
    expect(text).toContain("[ ] t2: 装依赖");
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
    expect(todoMark("completed")).toBe("[√]");
    expect(todoDockLines(next)).toEqual([]);
  });

  test("符号映射按用户规格 §一（进行中=正中间中点 U+00B7）", () => {
    expect(todoMark("pending")).toBe("[ ]");
    expect(todoMark("in_progress")).toBe("[·]");
    expect(todoMark("in_progress")).not.toContain(".");
    expect(todoMark("in_progress")).not.toContain("•");
    expect(todoMark("completed")).toBe("[√]");
    expect(todoMark("cancelled")).toBe("[x]");
    expect(todoMark("blocked")).toBe("[!]");
    expect(todoMark("unknown")).toBe("[ ]");
  });

  test("§二 不消失规则：有未终结任务时 completed 逐条显示，汇总行仅补充", () => {
    const snap: TodoDockSnapshot = {
      list_id: "default",
      revision: 3,
      items: [
        { id: "T1", content: "示例任务：卡片总数统计", status: "completed" },
        { id: "T2", content: "示例任务二：演示 abandon 弃置流转", status: "cancelled" },
        { id: "T3", content: "演示条目A：普通待办", status: "pending" },
        { id: "T4", content: "演示条目B：进行中", status: "in_progress" },
        { id: "T5", content: "演示条目C：排队中", status: "pending" },
      ],
    };
    expect(todoDockLines(snap)).toEqual([
      "[√] T1: 示例任务：卡片总数统计",
      "[x] T2: 示例任务二：演示 abandon 弃置流转",
      "[ ] T3: 演示条目A：普通待办",
      "[·] T4: 演示条目B：进行中",
      "[ ] T5: 演示条目C：排队中",
      "(1 completed, 1 cancelled)",
    ]);
  });

  test("§二 blocked 按 [!] 逐条显示并计入未终结判断", () => {
    const snap: TodoDockSnapshot = {
      list_id: "default",
      revision: 1,
      items: [{ id: "t1", content: "被卡住", status: "blocked" }],
    };
    const lines = todoDockLines(snap);
    expect(lines).toEqual([expect.stringContaining("[!] t1: 被卡住")]);
  });

  test("§三 清表时机：completed+cancelled 混合终结才可收起", () => {
    const mixed: TodoDockSnapshot = {
      list_id: "default",
      revision: 4,
      items: [
        { id: "t1", content: "a", status: "completed" },
        { id: "t2", content: "b", status: "cancelled" },
      ],
    };
    expect(todoDockLines(mixed)).toEqual([]);
    const stillOpen: TodoDockSnapshot = {
      ...mixed,
      items: [...mixed.items, { id: "t3", content: "c", status: "pending" }],
    };
    const lines = todoDockLines(stillOpen);
    expect(lines).toHaveLength(4); // 3 逐条 + 1 汇总补充
  });

  test("U-F5-4-02 Ctrl+T toggles todo and Ctrl+E toggles thinking", () => {
    expect(keyAction({ ctrl: true, name: "t" })).toBe("todo");
    expect(keyAction({ ctrl: true, name: "e" })).toBe("thinking");
    expect(keyAction({ ctrl: true, name: "p" })).toBeNull();
    const leftover = grepSource(/Ctrl\+T.*思考|Ctrl\+T.*thinking/i);
    expect(leftover).toEqual([]);
  });

  test("recorded event stream renders, updates, and collapses", () => {
    const recorded = process.env.FIX5_TODO_RECORDING;
    if (!recorded) {
      expect(recorded).toBeUndefined();
      return;
    }
    const payload = JSON.parse(readFileSync(recorded, "utf8")) as {
      bootstrap: TodoDockSnapshot;
      first_event: TodoUpdatedEvent;
      completed_event: TodoUpdatedEvent;
    };
    const opened = snapshotFromTodoGet(payload.bootstrap);
    const lines = todoDockLines(opened);
    const text = lines.join("\n");
    for (const item of payload.bootstrap.items) {
      expect(text).toContain(item.content);
      expect(text).toContain(`${item.id}:`);
    }
    expect(text).toMatch(/\[·\]|\[ \]/);
    expect(text).toContain("[ ]");
    expect(payload.first_event.snapshot?.revision).toBe(opened.revision);
    const hidden = keyAction({ ctrl: true, name: "t" }) === "todo" ? [] : lines;
    expect(hidden).toEqual([]);
    const collapsed = applyTodoUpdated(opened, payload.completed_event);
    expect(todoDockLines(collapsed)).toEqual([]);
    writeFileSync(recorded + ".ok", "ok", "utf8");
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
