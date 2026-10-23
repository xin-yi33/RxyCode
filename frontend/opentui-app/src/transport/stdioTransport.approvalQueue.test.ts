import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { StdioAppserverSession, __setPythonCmdForTests } from "./stdioTransport.ts";

function pythonForFixture(): string {
  const configured = process.env.RXYCODE_APPSERVER_PYTHON?.trim();
  if (configured) return configured;
  return process.platform === "win32" ? "python" : "python3";
}

const fixtureFixed = `
import json, sys
mode = sys.argv[1]
pending = []
held = None
for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get("method")
    if method is None:
        rid = str(msg.get("id"))
        if rid in ("A", "B"):
            pending.append(rid)
        if mode == "pair" and pending == ["A", "B"] and held is not None:
            print(json.dumps({"jsonrpc":"2.0","id":held,"result":{"text":"both closed","status":"succeeded"}}), flush=True)
        elif mode == "cancel" and pending == ["A"] and held is not None:
            print(json.dumps({"jsonrpc":"2.0","id":held,"result":{"text":"cancelled","status":"succeeded"}}), flush=True)
        continue
    if method == "initialize":
        result = {"capabilities": {}}
    elif method == "session/new":
        result = {"session_id": "audit-session", "model_id": "audit/model"}
    elif method == "session/prompt":
        held = msg["id"]
        if mode == "pair":
            print(json.dumps({"jsonrpc":"2.0","id":"A","method":"approval/request","params":{"request_id":"A","risk_level":"WRITE","action":"mcp_a","details":{"args":{},"description":"first"}}}), flush=True)
            print(json.dumps({"jsonrpc":"2.0","id":"B","method":"approval/request","params":{"request_id":"B","risk_level":"WRITE","action":"mcp_b","details":{"args":{},"description":"second"}}}), flush=True)
            print(json.dumps({"jsonrpc":"2.0","method":"event/progress","params":{"text":"BOTH_QUEUED"}}), flush=True)
        else:
            print(json.dumps({"jsonrpc":"2.0","id":"A","method":"approval/request","params":{"request_id":"A","risk_level":"WRITE","action":"mcp_a","details":{"args":{},"description":"only"}}}), flush=True)
        continue
    elif method == "audit/ping":
        result = {"pong": True}
    elif method == "shutdown":
        result = {}
    else:
        result = {}
    if "id" in msg:
        print(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":result}), flush=True)
    if method == "shutdown":
        break
`;

function start(mode: string): StdioAppserverSession {
  const dir = mkdtempSync(path.join(tmpdir(), "rxy-approval-"));
  const script = path.join(dir, "peer.py");
  writeFileSync(script, fixtureFixed, "utf8");
  process.env.RXYCODE_PROJECT_ROOT = dir;
  process.env.RXYCODE_DATA_DIR = dir;
  process.env.RXYCODE_APPSERVER_INIT_TIMEOUT_MS = "2000";
  process.env.RXYCODE_APPSERVER_SESSION_TIMEOUT_MS = "2000";
  __setPythonCmdForTests([pythonForFixture(), "-B", "-u", script, mode]);
  return new StdioAppserverSession();
}

async function until(ready: () => boolean): Promise<void> {
  const deadline = Date.now() + 2000;
  while (!ready()) {
    if (Date.now() > deadline) throw new Error("timed out waiting for approval queue");
    await new Promise((resolve) => setTimeout(resolve, 15));
  }
}

afterEach(() => {
  __setPythonCmdForTests(null);
});

test("two approvals stay queued by request id and a sibling ping still returns", async () => {
  const session = start("pair");
  const shown: Array<string | null> = [];
  const progress: string[] = [];
  try {
    const client = await session.ensureReady();
    const prompt = session.sendChatMessage("queue two approvals", "build", {
      onMessages: () => {},
      onStreaming: () => {},
      onStatus: () => {},
      onProgress: (text) => progress.push(text),
      onApprovalRequest: (info) => shown.push(info ? info.approvalId : null),
    });
    await until(() => progress.includes("BOTH_QUEUED"));
    expect(shown).toEqual(["A"]);
    const pong = await client.requestWithTimeout("audit/ping", {}, 500);
    expect(pong).toEqual({ pong: true });
    expect(shown).toEqual(["A"]);
    expect(session.resolveApproval("A", "rejected")).toBe(true);
    await until(() => shown.includes("B"));
    expect(shown).toEqual(["A", "B"]);
    expect(session.resolveApproval("B", "rejected")).toBe(true);
    await until(() => shown.at(-1) === null);
    expect(shown).toEqual(["A", "B", null]);
    await prompt;
    expect(session.resolveApproval("A", "approved")).toBe(false);
    expect(session.resolveApproval("B", "approved")).toBe(false);
  } finally {
    await session.shutdown();
  }
});

test("cancel and disconnect settle every waiting approval", async () => {
  const cancelSession = start("cancel");
  try {
    await cancelSession.ensureReady();
    const shown: Array<string | null> = [];
    const prompt = cancelSession.sendChatMessage("cancel me", "build", {
      onMessages: () => {},
      onStreaming: () => {},
      onStatus: () => {},
      onApprovalRequest: (info) => shown.push(info ? info.approvalId : null),
    });
    await until(() => shown[0] === "A");
    await cancelSession.interrupt();
    await until(() => shown.includes(null));
    await prompt;
    expect(cancelSession.resolveApproval("A", "approved")).toBe(false);
  } finally {
    await cancelSession.shutdown();
  }

  const dropSession = start("drop");
  try {
    await dropSession.ensureReady();
    let saw = false;
    const prompt = dropSession.sendChatMessage("drop me", "build", {
      onMessages: () => {},
      onStreaming: () => {},
      onStatus: () => {},
      onApprovalRequest: (info) => {
        if (info) saw = true;
      },
    });
    await until(() => saw);
    await dropSession.shutdown();
    await prompt;
    expect(dropSession.resolveApproval("A", "approved")).toBe(false);
  } finally {
    __setPythonCmdForTests(null);
  }
});
