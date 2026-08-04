import { describe, expect, test } from "bun:test";
import { classifyInput, formatCommandResult } from "./commandRouter.ts";
import { filterCommands, isSlashCommand, resolveSlashSubmit, isBareModelPickerCommand } from "./commands.ts";

describe("classifyInput", () => {
  test("hello is chat", () => {
    expect(classifyInput("你好")).toEqual({ kind: "chat", text: "你好" });
  });

  test("/model never chat", () => {
    const c = classifyInput("/model");
    expect(c.kind).toBe("command");
    if (c.kind === "command") {
      expect(c.name).toBe("/model");
      expect(c.args).toBe("");
      expect(c.local).toBe(false);
    }
  });

  test("/model with args", () => {
    const c = classifyInput("/model glm-5.2");
    expect(c.kind).toBe("command");
    if (c.kind === "command") {
      expect(c.name).toBe("/model");
      expect(c.args).toBe("glm-5.2");
    }
  });

  test("local commands", () => {
    for (const name of ["/clear", "/build", "/plan", "/compose", "/thinking", "/help"]) {
      const c = classifyInput(name);
      expect(c.kind).toBe("command");
      if (c.kind === "command") expect(c.local).toBe(true);
    }
  });
});

describe("filterCommands", () => {
  test("/mo matches model commands", () => {
    const names = filterCommands("/mo").map((c) => c.name);
    expect(names.some((n) => n.includes("model"))).toBe(true);
  });
});

describe("resolveSlashSubmit", () => {
  test("Enter on partial prefix runs highlighted suggestion", () => {
    const suggestions = filterCommands("/addmo");
    expect(suggestions.some((c) => c.name === "/addmodel")).toBe(true);
    const idx = suggestions.findIndex((c) => c.name === "/addmodel");
    expect(resolveSlashSubmit("/addmo", idx)).toBe("/addmodel");
  });

  test("Enter uses currently highlighted item among /addm matches", () => {
    const suggestions = filterCommands("/addm");
    const idx = suggestions.findIndex((c) => c.name === "/addmodel");
    expect(idx).toBeGreaterThanOrEqual(0);
    expect(resolveSlashSubmit("/addm", idx)).toBe("/addmodel");
  });

  test("preserves args after expanding prefix", () => {
    const suggestions = filterCommands("/mo");
    const model = suggestions.find((c) => c.name === "/model");
    expect(model).toBeDefined();
    const idx = suggestions.indexOf(model!);
    expect(resolveSlashSubmit("/mo glm-5", idx)).toBe("/model glm-5");
  });

  test("/mod expands to /model on Enter (fresh suggestions)", () => {
    expect(resolveSlashSubmit("/mod")).toBe("/model");
  });

  test("exact command name is not rewritten to a longer sibling", () => {
    expect(resolveSlashSubmit("/model")).toBe("/model");
  });

  test("non-slash text is unchanged", () => {
    expect(resolveSlashSubmit("hello")).toBe("hello");
  });
});

describe("isBareModelPickerCommand", () => {
  test("/model and /models without args open picker", () => {
    expect(isBareModelPickerCommand("/model", "")).toBe(true);
    expect(isBareModelPickerCommand("/models", "")).toBe(true);
    expect(isBareModelPickerCommand("/model", "glm-5")).toBe(false);
    expect(isBareModelPickerCommand("/mod", "")).toBe(false);
  });
});

describe("isSlashCommand", () => {
  test("detects slash", () => {
    expect(isSlashCommand("/model")).toBe(true);
    expect(isSlashCommand("你好")).toBe(false);
    expect(isSlashCommand("/路径")).toBe(false);
  });
});

describe("formatCommandResult", () => {
  test("uses message field", () => {
    expect(formatCommandResult({ message: "ok" }, "/x")).toBe("ok");
  });
  test("null fallback", () => {
    expect(formatCommandResult(null, "/x")).toContain("/x");
  });
});
