/**
 * ConPTY repro: /model and /mod + Enter must open the model dialog.
 * Run: node e2e/model-enter-verify.mjs
 * (Use node, not bun, to drive node-pty on Windows ConPTY.)
 */
import { createServer } from "node:http";
import { spawnSync } from "node:child_process";
import { spawn } from "node-pty";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { homedir } from "node:os";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const ANSI = /\x1b\[[0-?]*[ -/]*[@-~]/g;
const plain = (s) => s.replace(ANSI, "");

function resolveBunBin() {
  if (process.env.BUN_BIN) return process.env.BUN_BIN;
  const candidates = [
    join(homedir(), ".bun", "bin", process.platform === "win32" ? "bun.exe" : "bun"),
    "bun",
  ];
  for (const c of candidates) {
    const probe = spawnSync(c, ["--version"], { encoding: "utf8" });
    if (probe.status === 0) return c;
  }
  return "bun";
}

/** Spawn OpenTUI inside ConPTY; avoid `bun run` wrapper on Windows. */
function spawnApp(apiUrl, envExtra = {}) {
  const bun = resolveBunBin();
  const baseEnv = {
    ...process.env,
    TERM: "xterm-256color",
    FORCE_COLOR: "1",
    RXYCODE_API_URL: apiUrl,
    RXYCODE_API_TOKEN: "e2e-token",
    RXYCODE_E2E_BYPASS_TTY: "1",
    RXYCODE_TRANSPORT: "http",
    CI: "false",
    ...envExtra,
  };
  const opts = {
    name: "xterm-256color",
    cwd: ROOT,
    cols: 100,
    rows: 32,
    env: baseEnv,
    ...(process.platform === "win32" ? { useConpty: true } : {}),
  };
  // Direct `bun src/index.tsx` is more reliable than `bun run` under ConPTY.
  return spawn(bun, ["src/index.tsx"], opts);
}

function startMockApi() {
  const server = createServer((req, res) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      if (req.method === "GET" && req.url === "/status") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ model: "m1", mode: "build", context_used_k: 1, context_max_k: 256 }));
        return;
      }
      if (req.method === "GET" && req.url === "/models") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(
          JSON.stringify({
            models: [
              { id: "provider/a", name: "provider/a", nickname: "Model A", category: "Provider" },
              { id: "provider/b", name: "provider/b", nickname: "Model B", category: "Provider" },
            ],
            active: "provider/a",
            recent: [],
          }),
        );
        return;
      }
      if (req.method === "POST" && req.url === "/command") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ action: "model_changed", message: "ok", ok: true }));
        return;
      }
      if (req.method === "POST" && req.url === "/chat/stream") {
        res.writeHead(200, { "content-type": "text/event-stream" });
        res.end(`data: ${JSON.stringify({ type: "final", text: "CHAT" })}\n\n`);
        return;
      }
      res.writeHead(404);
      res.end("{}");
    });
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      resolve({
        url: `http://127.0.0.1:${addr.port}`,
        close: () => new Promise((d) => server.close(d)),
      });
    });
  });
}

async function runCase(label, typed) {
  const api = await startMockApi();
  let pty;
  let output = "";
  let exited = false;
  try {
    pty = spawnApp(api.url);
    pty.onData((chunk) => {
      output += chunk;
    });
    pty.onExit(() => {
      exited = true;
    });

    const waitFor = (pred, name, ms = 15000) =>
      new Promise((resolve, reject) => {
        const t0 = Date.now();
        const tick = () => {
          if (pred(output)) return resolve();
          if (Date.now() - t0 > ms) {
            const tail = plain(output.slice(-900)).replace(/\s+/g, " ").trim();
            return reject(new Error(`${name} timeout; tail=${tail}`));
          }
          setTimeout(tick, 40);
        };
        tick();
      });

    await waitFor(
      (o) => /RxyCode/.test(plain(o)) && /Ready|online|Build/.test(plain(o)),
      "boot",
      25000,
    );
    await new Promise((r) => setTimeout(r, 800));

    // If add-model wizard auto-opened, Esc close it first.
    if (/添加模型|API Key|Discover|连接预设/.test(plain(output))) {
      pty.write("\x1b");
      await new Promise((r) => setTimeout(r, 400));
    }

    const before = output.length;
    for (const ch of typed) {
      pty.write(ch);
      await new Promise((r) => setTimeout(r, 80));
    }
    await new Promise((r) => setTimeout(r, 400));
    const afterType = plain(output.slice(before));
    console.log(`TYPED_SLICE[${label}]:`, JSON.stringify(afterType.slice(0, 400)));
    pty.write("\r");
    await new Promise((r) => setTimeout(r, 1200));
    const afterEnter = plain(output.slice(before));
    console.log(`ENTER_SLICE[${label}]:`, JSON.stringify(afterEnter.slice(0, 600)));

    const hasModelDialog =
      /选择模型/.test(afterEnter) && /Model A|provider\/a/.test(afterEnter);
    const onlyPalette =
      /命令建议/.test(afterEnter) && !/选择模型/.test(afterEnter);
    const ok = hasModelDialog && !onlyPalette;
    console.log(`${ok ? "PASS" : "FAIL"}  ${label}`);
    return ok;
  } finally {
    try {
      if (!exited && pty) {
        pty.write("\x03");
        await new Promise((r) => setTimeout(r, 300));
      }
    } catch {
      /* ignore */
    }
    await new Promise((r) => setTimeout(r, 500));
    try {
      if (!exited && pty) pty.kill();
    } catch {
      /* ignore */
    }
    await new Promise((r) => setTimeout(r, 500));
    await api.close();
  }
}

const ok1 = await runCase("/model Enter", "/model");
await new Promise((r) => setTimeout(r, 800));
const ok2 = await runCase("/mod Enter", "/mod");
console.log(`\n=== model-enter-verify: ${ok1 && ok2 ? "PASS" : "FAIL"} ===`);
process.exit(ok1 && ok2 ? 0 : 1);
