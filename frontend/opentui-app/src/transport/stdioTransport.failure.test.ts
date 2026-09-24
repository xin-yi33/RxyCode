import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  __resetStdioSessionForTests,
  __setPythonCmdForTests,
} from "./stdioTransport.ts";
import { resetChatTransportForTests, getChatTransport } from "./index.ts";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../..",
);
const fixturesDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../test-fixtures",
);
const python = process.env.PYTHON ?? "python";

async function runStartupFailureCase(
  setup: () => void,
  timeoutMs = 15_000,
): Promise<{ streaming: boolean; progress: string }> {
  process.env.RXYCODE_TRANSPORT = "stdio";
  process.env.RXYCODE_PROJECT_ROOT = repoRoot;
  process.env.RXYCODE_APPSERVER_INIT_TIMEOUT_MS = "500";
  process.env.RXYCODE_APPSERVER_SESSION_TIMEOUT_MS = "500";
  delete process.env.RXYCODE_APPSERVER_STUB;

  setup();

  const transport = getChatTransport();
  let streaming = false;
  let progress = "";

  await transport.sendChatMessage("你好", "build", {
    onMessages: () => {},
    onStreaming: (value) => {
      streaming = value;
    },
    onProgress: (text) => {
      progress = text;
    },
    onStatus: () => {},
  });

  await transport.shutdown?.();
  return { streaming, progress };
}

describe("stdio transport startup failures", () => {
  afterEach(() => {
    __resetStdioSessionForTests();
    resetChatTransportForTests();
    delete process.env.RXYCODE_TRANSPORT;
    delete process.env.RXYCODE_PROJECT_ROOT;
    delete process.env.RXYCODE_APPSERVER_PYTHON;
    delete process.env.RXYCODE_APPSERVER_INIT_TIMEOUT_MS;
    delete process.env.RXYCODE_APPSERVER_SESSION_TIMEOUT_MS;
  });

  test("invalid python executable does not stay Connecting", async () => {
    const result = await runStartupFailureCase(() => {
      process.env.RXYCODE_APPSERVER_PYTHON = "C:\\nonexistent\\rxycode-python.exe";
      __setPythonCmdForTests(null);
    });
    expect(result.streaming).toBe(false);
    expect(result.progress).toBe("");
  }, 20_000);

  test("listSessions restarts a dead appserver and still returns the catalog", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "rxy-appserver-restart-"));
    const marker = path.join(dir, "seen");
    const script = path.join(dir, "stub_appserver.py");
    writeFileSync(
      script,
      [
        "import json, os, sys",
        "marker = sys.argv[1]",
        "if not os.path.exists(marker):",
        "    open(marker, 'w', encoding='utf-8').write('1')",
        "    raise SystemExit(1)",
        "for line in sys.stdin:",
        "    msg = json.loads(line)",
        "    mid = msg.get('id')",
        "    method = msg.get('method')",
        "    if method == 'initialize':",
        "        result = {'protocol_version': '1.1.0', 'protocol_min': '1.0.0', 'protocol_max': '1.1.0', 'server_name': 'rxycode-appserver', 'server_version': '1.4.0', 'capabilities': {}}",
        "    elif method == 'session/new':",
        "        result = {'session_id': 's1', 'workspace_root': '.'}",
        "    elif method == 'sessions/list':",
        "        result = {'sessions': [{'session_id': 'kept', 'title': 'kept', 'display_title': 'kept', 'workspace_root': '.'}]}",
        "    elif method == 'shutdown':",
        "        result = {'ok': True}",
        "    else:",
        "        continue",
        "    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': result}) + '\\n')",
        "    sys.stdout.flush()",
        "    if method == 'shutdown':",
        "        break",
        "",
      ].join("\n"),
      "utf-8",
    );
    process.env.RXYCODE_TRANSPORT = "stdio";
    process.env.RXYCODE_PROJECT_ROOT = repoRoot;
    __setPythonCmdForTests([python, script, marker]);
    const rows = await getChatTransport().listSessions();
    expect(rows.map((row) => row.session_id)).toEqual(["kept"]);
    await getChatTransport().shutdown?.();
  }, 20_000);

  test("appserver immediate exit does not stay Connecting", async () => {
    const result = await runStartupFailureCase(() => {
      __setPythonCmdForTests([python, "-c", "import sys; sys.exit(1)"]);
    });
    expect(result.streaming).toBe(false);
    expect(result.progress).toBe("");
  }, 20_000);

  test("initialize no response times out", async () => {
    const result = await runStartupFailureCase(() => {
      __setPythonCmdForTests([python, path.join(fixturesDir, "silent_appserver.py")]);
    });
    expect(result.streaming).toBe(false);
    expect(result.progress).toBe("");
  }, 20_000);

  test("session/new no response times out", async () => {
    const result = await runStartupFailureCase(() => {
      __setPythonCmdForTests([python, path.join(fixturesDir, "init_only_appserver.py")]);
    });
    expect(result.streaming).toBe(false);
    expect(result.progress).toBe("");
  }, 20_000);

  test("thought placeholder is pushed before ensureReady (FX7)", async () => {
    process.env.RXYCODE_TRANSPORT = "stdio";
    process.env.RXYCODE_PROJECT_ROOT = repoRoot;
    process.env.RXYCODE_APPSERVER_INIT_TIMEOUT_MS = "500";
    process.env.RXYCODE_APPSERVER_SESSION_TIMEOUT_MS = "500";
    __setPythonCmdForTests([python, "-c", "import sys; sys.exit(1)"]);

    const transport = getChatTransport();
    const snapshots: Array<{ role: string; live?: boolean; done?: boolean }[]> = [];
    let acc: import("../types.ts").ChatMessage[] = [];
    await transport.sendChatMessage("你好", "build", {
      onMessages: (updater) => {
        acc = updater(acc);
        snapshots.push(
          acc.map((m) => ({
            role: m.role,
            live: "live" in m ? (m.live as boolean) : undefined,
            done: "done" in m ? (m.done as boolean) : undefined,
          })),
        );
      },
      onStreaming: () => {},
      onProgress: () => {},
      onStatus: () => {},
    });

    // Startup fails (worker exits), yet the assistant "…" row must already
    // have been pushed before ensureReady ever resolved/rejected — the
    // placeholder can only originate from the pre-ensureReady section.
    const placeholderSeen = snapshots.some((roles) =>
      roles.some(
        (m) => m.role === "thinking" && m.live === true && m.done === false,
      ),
    );
    expect(placeholderSeen).toBe(true);
    // The placeholder must not dangle: the same thinking row settles to
    // done/live:false before the call finishes.
    const settledSeen = snapshots.some((roles) =>
      roles.some(
        (m) => m.role === "thinking" && m.live === false && m.done === true,
      ),
    );
    expect(settledSeen).toBe(true);

    await transport.shutdown?.();
  }, 20_000);
});
