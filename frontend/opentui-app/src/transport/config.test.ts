import { afterEach, describe, expect, test } from "bun:test";
import { resolveTransportKind } from "./config.ts";
import { getChatTransport, resetChatTransportForTests } from "./index.ts";

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

  test("cached client follows a later RXYCODE_TRANSPORT change", () => {
    const prev = process.env.RXYCODE_TRANSPORT;
    process.env.RXYCODE_TRANSPORT = "http";
    resetChatTransportForTests();
    expect(getChatTransport().kind).toBe("http");
    process.env.RXYCODE_TRANSPORT = "stdio";
    expect(getChatTransport().kind).toBe("stdio");
    resetChatTransportForTests();
    if (prev !== undefined) process.env.RXYCODE_TRANSPORT = prev;
    else delete process.env.RXYCODE_TRANSPORT;
  });
});

afterEach(() => {
  resetChatTransportForTests();
});
