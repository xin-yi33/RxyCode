import { describe, expect, test } from "bun:test";
import { sanitizeCopiedText } from "./copySanitize.ts";

describe("sanitizeCopiedText", () => {
  test("drops user-frame bars and rule lines", () => {
    const raw = [
      "█────────────────────────────────────────",
      "█ 打开",
      "█────────────────────────────────────────",
    ].join("\n");
    expect(sanitizeCopiedText(raw)).toBe("打开");
  });

  test("keeps ordinary assistant text", () => {
    expect(sanitizeCopiedText("你好！\n下一行")).toBe("你好！\n下一行");
  });
});
