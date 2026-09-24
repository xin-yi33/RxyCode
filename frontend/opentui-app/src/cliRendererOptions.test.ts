import { describe, expect, test } from "bun:test";
import {
  consumeSgrMouseInput,
  resolveCliRendererMouseOptions,
} from "./cliRendererOptions.ts";

describe("resolveCliRendererMouseOptions", () => {
  test("win32 keeps clicks/wheel/drag and leaves all-motion off", () => {
    expect(
      resolveCliRendererMouseOptions({ WT_SESSION: "1" }, "win32"),
    ).toEqual({ useMouse: true, enableMouseMovement: false });
    expect(resolveCliRendererMouseOptions({}, "win32")).toEqual({
      useMouse: true,
      enableMouseMovement: false,
    });
  });

  test("RXYCODE_MOUSE_MOVE=0 turns hover tracking off", () => {
    expect(
      resolveCliRendererMouseOptions({ RXYCODE_MOUSE_MOVE: "0" }, "win32"),
    ).toEqual({ useMouse: true, enableMouseMovement: false });
  });

  test("RXYCODE_MOUSE=0 disables tracking", () => {
    expect(
      resolveCliRendererMouseOptions({ RXYCODE_MOUSE: "0" }, "win32"),
    ).toEqual({ useMouse: false, enableMouseMovement: false });
  });

  test("RXYCODE_MOUSE_MOVE=1 opts into all-motion", () => {
    expect(
      resolveCliRendererMouseOptions({ RXYCODE_MOUSE_MOVE: "1" }, "win32"),
    ).toEqual({ useMouse: true, enableMouseMovement: true });
  });

  test("unix keeps click and movement tracking", () => {
    expect(resolveCliRendererMouseOptions({}, "linux")).toEqual({
      useMouse: true,
      enableMouseMovement: true,
    });
  });
});

describe("consumeSgrMouseInput", () => {
  test("eats hover-only SGR and leaves click/wheel/drag", () => {
    expect(consumeSgrMouseInput("\x1b[<35;46;17M")).toBe(true);
    expect(consumeSgrMouseInput("[<35;46;17M")).toBe(true);
    expect(consumeSgrMouseInput("\x1b[<0;10;12M")).toBe(false);
    expect(consumeSgrMouseInput("\x1b[<32;10;12M")).toBe(false);
    expect(consumeSgrMouseInput("\x1b[<64;10;12M")).toBe(false);
    expect(consumeSgrMouseInput("hello")).toBe(false);
    expect(consumeSgrMouseInput("\x1b[<35;50")).toBe(true);
    expect(consumeSgrMouseInput("[<35;50;19")).toBe(true);
  });
});
