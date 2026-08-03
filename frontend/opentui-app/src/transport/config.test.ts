import { describe, expect, test } from "bun:test";
import { resolveTransportKind } from "./config.ts";

describe("resolveTransportKind", () => {
  test("defaults to stdio", () => {
    const prev = process.env.RXYCODE_TRANSPORT;
    delete process.env.RXYCODE_TRANSPORT;
    expect(resolveTransportKind()).toBe("stdio");
    if (prev !== undefined) process.env.RXYCODE_TRANSPORT = prev;
  });

  test("accepts http fallback", () => {
    const prev = process.env.RXYCODE_TRANSPORT;
    process.env.RXYCODE_TRANSPORT = "http";
    expect(resolveTransportKind()).toBe("http");
    if (prev !== undefined) process.env.RXYCODE_TRANSPORT = prev;
    else delete process.env.RXYCODE_TRANSPORT;
  });

  test("accepts stdio explicitly", () => {
    const prev = process.env.RXYCODE_TRANSPORT;
    process.env.RXYCODE_TRANSPORT = "stdio";
    expect(resolveTransportKind()).toBe("stdio");
    if (prev !== undefined) process.env.RXYCODE_TRANSPORT = prev;
    else delete process.env.RXYCODE_TRANSPORT;
  });
});
