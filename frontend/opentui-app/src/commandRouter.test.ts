import { describe, expect, test } from "bun:test";
import { classifyInput, formatCommandResult } from "./commandRouter.ts";
import { filterCommands, isSlashCommand } from "./commands.ts";

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
