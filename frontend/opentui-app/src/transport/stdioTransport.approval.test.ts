import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resetChatTransportForTests } from "./index.ts";
import { __resetStdioSessionForTests } from "./stdioTransport.ts";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../..",
);
const appRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);

describe("stdio transport approval lifecycle", () => {
  beforeEach(() => {
    __resetStdioSessionForTests();
    resetChatTransportForTests();
  });

  afterEach(() => {
    __resetStdioSessionForTests();
    resetChatTransportForTests();
    delete process.env.RXYCODE_TRANSPORT;
    delete process.env.RXYCODE_APPSERVER_STUB;
    delete process.env.RXYCODE_PROJECT_ROOT;
    delete process.env.RXYCODE_APPSERVER_PYTHON;
  });

  test("p5 stdio smoke script exits cleanly", async () => {
    const proc = Bun.spawn(["bun", "run", "scripts/p5-stdio-smoke.ts"], {
      cwd: appRoot,
      env: {
        ...process.env,
        RXYCODE_TRANSPORT: "stdio",
        RXYCODE_APPSERVER_STUB: "1",
        RXYCODE_PROJECT_ROOT: repoRoot,
        RXYCODE_APPSERVER_PYTHON:
          process.env.RXYCODE_APPSERVER_PYTHON ??
          process.env.PYTHON ??
          "python",
      },
      stdout: "pipe",
      stderr: "pipe",
    });

    const exitCode = await Promise.race([
      proc.exited,
      new Promise<number>((_, reject) =>
        setTimeout(() => reject(new Error("p5-stdio-smoke timed out")), 45_000),
      ),
    ]);

    expect(exitCode).toBe(0);
  }, 60_000);
});
