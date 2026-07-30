import { describe, expect, test } from "bun:test";
import { filterAndGroup, CATEGORY_ORDER } from "./CommandPalette.group.ts";

describe("filterAndGroup", () => {
  test("empty query groups by category with headers before items", () => {
    const { flat, rows } = filterAndGroup("");
    expect(flat.length).toBeGreaterThan(10);
    expect(rows.some((r) => r.kind === "header")).toBe(true);
    expect(rows.some((r) => r.kind === "item")).toBe(true);

    // No header may immediately follow another header without items in between
    // (each category header precedes its items).
    let lastWasHeader = false;
    for (const r of rows) {
      if (r.kind === "header") {
        expect(lastWasHeader).toBe(false);
        lastWasHeader = true;
      } else if (r.kind === "item") {
        lastWasHeader = false;
      }
    }
  });

  test("category order follows CATEGORY_ORDER", () => {
    const { rows } = filterAndGroup("");
    const cats = rows.filter((r) => r.kind === "header").map((r) => (r as { category: string }).category);
    const idxs = cats.map((c) => CATEGORY_ORDER.indexOf(c)).filter((i) => i >= 0);
    for (let i = 1; i < idxs.length; i++) {
      expect(idxs[i]).toBeGreaterThanOrEqual(idxs[i - 1]);
    }
  });

  test("search flattens — no category headers", () => {
    const { rows } = filterAndGroup("addmodel");
    expect(rows.every((r) => r.kind === "item")).toBe(true);
    expect(rows.some((r) => r.kind === "item" && r.cmd.name === "/addmodel")).toBe(true);
  });

  test("known commands keep Chinese description and correct category", () => {
    const { flat } = filterAndGroup("");
    const addmodel = flat.find((c) => c.name === "/addmodel");
    expect(addmodel?.description).toBe("添加新模型");
    expect(addmodel?.category).toBe("Agent");

    const addskill = flat.find((c) => c.name === "/addskill");
    expect(addskill?.description).toBe("从 URL 或名称安装 skill");
    expect(addskill?.category).toBe("Skills");

    const clear = flat.find((c) => c.name === "/clear");
    expect(clear?.description).toBe("清除对话上下文");
    expect(clear?.category).toBe("会话");
  });

  test("flatIndex is contiguous across items only", () => {
    const { flat, rows } = filterAndGroup("");
    const items = rows.filter((r) => r.kind === "item") as Array<{ flatIndex: number }>;
    expect(items.length).toBe(flat.length);
    items.forEach((it, i) => expect(it.flatIndex).toBe(i));
  });
});
