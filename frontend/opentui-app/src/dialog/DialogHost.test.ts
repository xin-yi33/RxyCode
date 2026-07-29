import { describe, expect, test } from "bun:test";
import { stackPop, stackPush, stackReplace } from "./DialogHost.tsx";

describe("DialogHost stack helpers", () => {
  test("replace yields single-node stack (legacy)", () => {
    const a = "palette";
    const b = "session";
    expect(stackReplace(["x", "y"], a)).toEqual([a]);
    expect(stackReplace([], b)).toEqual([b]);
  });

  test("push appends without dropping parent", () => {
    const s0 = stackReplace([], "list");
    const s1 = stackPush(s0, "confirm");
    expect(s1).toEqual(["list", "confirm"]);
  });

  test("pop from depth 2 returns parent", () => {
    const s = stackPush(stackReplace([], "list"), "confirm");
    expect(stackPop(s)).toEqual(["list"]);
  });

  test("pop from depth 1 clears (same as clear)", () => {
    expect(stackPop(["only"])).toEqual([]);
    expect(stackPop([])).toEqual([]);
  });
});
