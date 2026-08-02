import { describe, expect, test } from "bun:test";
import { resolveTransportKind } from "./config.ts";

describe("resolveTransportKind", () => {
  test("defaults to http", () => {
    const prev = process.env.RXYCODE_TRANSPORT;
    delete process.env.RXYCODE_TRANSPORT;
    expect(resolveTransportKind()).toBe("http");
    if (prev !== undefined) process.env.RXYCODE_TRANSPORT = prev;
  });

  test("accepts stdio", () => {
    const prev = process.env.RXYCODE_TRANSPORT;
    process.env.RXYCODE_TRANSPORT = "stdio";
    expect(resolveTransportKind()).toBe("stdio");
    if (prev !== undefined) process.env.RXYCODE_TRANSPORT = prev;
    else delete process.env.RXYCODE_TRANSPORT;
  });
});
