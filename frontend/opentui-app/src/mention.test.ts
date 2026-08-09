import { describe, expect, test } from "bun:test";
import { parseMention } from "./mention.ts";

describe("parseMention", () => {
  test("parses @agent with prompt", () => {
    expect(parseMention("@explore 查找认证模块")).toEqual({
      agentId: "explore",
      prompt: "查找认证模块",
    });
  });

  test("parses bare @agent without prompt", () => {
    expect(parseMention("@reviewer")).toEqual({ agentId: "reviewer", prompt: "" });
  });

  test("supports agent ids with digits and dashes", () => {
    expect(parseMention("@code-review-2 看 diff")).toEqual({
      agentId: "code-review-2",
      prompt: "看 diff",
    });
  });

  test("returns null when not a mention", () => {
    expect(parseMention("explore 查找")).toBeNull();
    expect(parseMention("@ 空格后无 id")).toBeNull();
    expect(parseMention("@@double")).toBeNull();
    expect(parseMention("@Uppercase")).toBeNull();
  });

  test("trims leading whitespace", () => {
    expect(parseMention("  @explore x")).toEqual({ agentId: "explore", prompt: "x" });
  });

  test("keeps multi-line prompt after the mention", () => {
    expect(parseMention("@explore 第一行\n第二行")).toEqual({
      agentId: "explore",
      prompt: "第一行\n第二行",
    });
  });
});
