import { afterEach, describe, expect, test } from "bun:test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { getChatTransport, resetChatTransportForTests } from "./index.ts";
import { __resetStdioSessionForTests } from "./stdioTransport.ts";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../..",
);

describe("stdio transport integration", () => {
  afterEach(() => {
    __resetStdioSessionForTests();
    resetChatTransportForTests();
    delete process.env.RXYCODE_TRANSPORT;
    delete process.env.RXYCODE_APPSERVER_STUB;
    delete process.env.RXYCODE_PROJECT_ROOT;
    delete process.env.RXYCODE_APPSERVER_PYTHON;
  });

  test("stub appserver prompt round-trip", async () => {
    process.env.RXYCODE_TRANSPORT = "stdio";
    process.env.RXYCODE_APPSERVER_STUB = "1";
    process.env.RXYCODE_PROJECT_ROOT = repoRoot;
    process.env.RXYCODE_APPSERVER_PYTHON =
      process.env.RXYCODE_APPSERVER_PYTHON ??
      process.env.PYTHON ??
      "python";

    const transport = getChatTransport();
    expect(transport.kind).toBe("stdio");

    const messages: import("../types.ts").ChatMessage[] = [];
    let streaming = false;

    await transport.sendChatMessage("hello", "build", {
      onMessages: (updater) => {
        messages.splice(0, messages.length, ...updater(messages));
      },
      onStreaming: (value) => {
        streaming = value;
      },
      onStatus: () => {},
    });

    expect(streaming).toBe(false);
    expect(messages.some((m) => m.role === "user" && m.content === "hello")).toBe(true);
    expect(
      messages.some(
        (m) => m.role === "assistant" && m.content.includes("stub:hello"),
      ),
    ).toBe(true);

    await transport.shutdown?.();
  }, 60_000);
});
