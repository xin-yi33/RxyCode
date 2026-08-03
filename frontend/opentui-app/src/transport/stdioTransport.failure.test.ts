import { afterEach, describe, expect, test } from "bun:test";
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
});
