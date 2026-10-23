import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { getChatTransport, resetChatTransportForTests } from "./index.ts";
import { __resetStdioSessionForTests, __setPythonCmdForTests } from "./stdioTransport.ts";

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
    __setPythonCmdForTests(null);
  });

  test("stub appserver prompt round-trip", async () => {
    process.env.RXYCODE_TRANSPORT = "stdio";
    process.env.RXYCODE_APPSERVER_STUB = "1";
    process.env.RXYCODE_PROJECT_ROOT = repoRoot;
    process.env.RXYCODE_APPSERVER_PYTHON =
      process.env.RXYCODE_APPSERVER_PYTHON ??
      process.env.PYTHON ??
      "python";
    resetChatTransportForTests();

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

  test("sends only lightweight attachment metadata when handshake opts in", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "rxy-clipboard-stdio-"));
    const script = path.join(dir, "attachment_appserver.py");
    const capturePath = path.join(dir, "received.json");
    writeFileSync(script, [
      "import json, sys",
      "for line in sys.stdin:",
      "    msg = json.loads(line)",
      "    method = msg.get('method')",
      "    params = msg.get('params', {})",
      "    if method == 'initialize': result = {'capabilities': {'prompt_attachments': True}}",
      "    elif method == 'session/new': result = {'session_id': 'clipboard-session'}",
      "    elif method == 'session/prompt':",
      "        open(sys.argv[1], 'w', encoding='utf-8').write(json.dumps(params.get('attachments', [])))",
      "        result = {'text': 'accepted'}",
      "    else: result = {}",
      "    if 'id' in msg:",
      "        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': result}) + '\\n')",
      "        sys.stdout.flush()",
      "    if method == 'shutdown': break",
      "",
    ].join("\n"), "utf-8");
    process.env.RXYCODE_TRANSPORT = "stdio";
    process.env.RXYCODE_PROJECT_ROOT = repoRoot;
    process.env.RXYCODE_APPSERVER_INIT_TIMEOUT_MS = "1000";
    process.env.RXYCODE_APPSERVER_SESSION_TIMEOUT_MS = "1000";
    __setPythonCmdForTests([process.env.PYTHON ?? "python", script, capturePath]);
    resetChatTransportForTests();
    const messages: import("../types.ts").ChatMessage[] = [];
    await getChatTransport().sendChatMessage("inspect", "build", {
      onMessages: (updater) => messages.splice(0, messages.length, ...updater(messages)),
      onStreaming: () => {},
      onStatus: () => {},
    }, undefined, undefined, [{ path: "C:\\tmp\\fixture.png", name: "fixture.png" }]);
    expect(JSON.parse(readFileSync(capturePath, "utf-8"))).toEqual([
      { path: "C:\\tmp\\fixture.png", name: "fixture.png" },
    ]);
    expect(messages.find((message) => message.role === "user")?.attachments).toEqual([
      { path: "C:\\tmp\\fixture.png", name: "fixture.png" },
    ]);
    await getChatTransport().shutdown?.();
  }, 20_000);
});
