/**
 * PTY verify: palette filter -> nested model / session / addmodel dialogs.
 */
import { createServer } from "node:http";
import { spawnSync } from "node:child_process";
import { spawn } from "node-pty";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { homedir } from "node:os";
import { writeFileSync } from "node:fs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const ANSI = /\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[PX^_].*?\x1b\\|\x1b./g;
const plain = (s) => s.replace(ANSI, "");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function resolveBunBin() {
  if (process.env.BUN_BIN) return process.env.BUN_BIN;
  const candidates = [
    join(homedir(), ".bun", "bin", process.platform === "win32" ? "bun.exe" : "bun"),
    "bun",
  ];
  for (const candidate of candidates) {
    const probe = spawnSync(candidate, ["--version"], { encoding: "utf8" });
    if (probe.status !== 0) continue;
    if (process.platform === "win32" && !/[\\/]/.test(candidate)) {
      const where = spawnSync("where.exe", [candidate], { encoding: "utf8" });
      const resolved = where.stdout?.split(/\r?\n/).map((l) => l.trim()).find(Boolean);
      if (resolved) return resolved;
    }
    return candidate;
  }
  return join(homedir(), ".bun", "bin", "bun.exe");
}

function startMockApi() {
  const server = createServer((req, res) => {
    const url = req.url || "";
    const json = (obj) => {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify(obj));
    };
    if (req.method === "GET" && url === "/status") {
      json({
        model: "pty-model",
        mode: "build",
        context_used_k: 1.2,
        context_max_k: 256,
        cache_size: "0B",
        cache_rate: "0%",
      });
      return;
    }
    if (req.method === "GET" && url === "/models") {
      json({
        models: [
          { id: "pty-model", name: "pty-model", nickname: "pty-model", active: true, base_url: "http://x" },
          { id: "other", name: "other-model", nickname: "other", active: false, base_url: "http://y" },
        ],
        active: "pty-model",
      });
      return;
    }
    if (req.method === "POST" && url === "/command") {
      let body = "";
      req.on("data", (c) => {
        body += c;
      });
      req.on("end", () => {
        let cmd = "";
        try {
          cmd = JSON.parse(body).command || "";
        } catch {
          /* */
        }
        if (cmd === "/session" || cmd === "/list-chats") {
          json({ chats: [{ name: "chat-a", preview: "hello", time: "today" }] });
          return;
        }
        if (cmd.startsWith("/load-chat")) {
          json({
            action: "loaded",
            message: "loaded ok",
            messages: [
              { role: "user", content: "hi" },
              { role: "assistant", content: "yo" },
            ],
          });
          return;
        }
        if (cmd.startsWith("/model ")) {
          json({ action: "model_changed", message: `switched ${cmd.slice(7)}` });
          return;
        }
        json({ message: `ok:${cmd}` });
      });
      return;
    }
    res.writeHead(404);
    res.end();
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port }));
  });
}

const { server, port } = await startMockApi();
const bun = resolveBunBin();
let buf = "";
let alive = true;
const pty = spawn(bun, ["run", "src/index.tsx"], {
  name: "xterm-256color",
  cols: 100,
  rows: 36,
  cwd: ROOT,
  env: {
    ...process.env,
    RXYCODE_API_BASE: `http://127.0.0.1:${port}`,
    RXYCODE_API_URL: `http://127.0.0.1:${port}`,
    RXYCODE_E2E_BYPASS_TTY: "1",
    RXYCODE_OPEN_PALETTE: "1",
    FORCE_COLOR: "1",
    TERM: "xterm-256color",
  },
  ...(process.platform === "win32" ? { useConpty: true } : {}),
});
pty.onData((d) => {
  buf += d;
});
pty.onExit(() => {
  alive = false;
});

function writeSafe(s) {
  if (!alive) return false;
  try {
    pty.write(s);
    return true;
  } catch {
    return false;
  }
}

async function waitFor(re, ms = 10000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (re.test(plain(buf))) return true;
    if (!alive) return false;
    await sleep(200);
  }
  return false;
}

const results = [];
function check(name, ok) {
  results.push({ name, ok });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
}

check("palette open", await waitFor(/命令/));
check("palette /clear", /\/clear/.test(plain(buf)));

for (const ch of "model") {
  writeSafe(ch);
  await sleep(100);
}
await sleep(800);
writeSafe("\r");
await sleep(2800);
check("model dialog", /选择模型/.test(plain(buf)));
check("model other", /other/.test(plain(buf)));
check("model add", /\+ 添加模型/.test(plain(buf)));

writeSafe("\x1b");
await sleep(600);
writeSafe("\x10");
await sleep(900);
for (const ch of "session") {
  writeSafe(ch);
  await sleep(80);
}
await sleep(600);
writeSafe("\r");
await sleep(2800);
check("session dialog", /切换会话/.test(plain(buf)));
check("session chat-a", /chat-a/.test(plain(buf)));

writeSafe("\x1b");
await sleep(600);
writeSafe("\x10");
await sleep(900);
for (const ch of "addmodel") {
  writeSafe(ch);
  await sleep(80);
}
await sleep(600);
writeSafe("\r");
await sleep(2800);
check("addmodel wizard", /添加模型/.test(plain(buf)));
check("addmodel step", /1\/4|Provider model ID/.test(plain(buf)));

writeFileSync(join(ROOT, "e2e", "nested-verify.txt"), plain(buf), "utf8");
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed; alive=${alive}`);
try {
  pty.kill();
} catch {
  /* */
}
server.close();
process.exit(failed ? 1 : 0);
