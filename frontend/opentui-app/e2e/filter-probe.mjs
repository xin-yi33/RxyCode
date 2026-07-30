import { spawn } from "node-pty";
import { createServer } from "node:http";
import { join } from "node:path";
import { homedir } from "node:os";

const ANSI = /\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[PX^_].*?\x1b\\|\x1b./g;
const plain = (s) => s.replace(ANSI, "");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const useConpty = process.argv.includes("--winpty") ? false : true;

const server = createServer((req, res) => {
  res.writeHead(200, { "content-type": "application/json" });
  if (req.url === "/status") {
    res.end(
      JSON.stringify({
        model: "pty-model",
        mode: "build",
        context_used_k: 1,
        context_max_k: 256,
        cache_size: "0B",
        cache_rate: "0%",
      }),
    );
  } else if (req.url === "/models") {
    res.end(JSON.stringify({ models: [{ id: "pty-model", name: "pty-model", active: true }], active: "pty-model" }));
  } else {
    res.end("{}");
  }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const port = server.address().port;
const bun = join(homedir(), ".bun", "bin", "bun.exe");
let buf = "";
let alive = true;
let exitInfo = null;
const pty = spawn(bun, ["run", "src/index.tsx"], {
  name: "xterm-256color",
  cols: 100,
  rows: 36,
  cwd: process.cwd(),
  env: {
    ...process.env,
    RXYCODE_API_URL: `http://127.0.0.1:${port}`,
    RXYCODE_API_BASE: `http://127.0.0.1:${port}`,
    RXYCODE_E2E_BYPASS_TTY: "1",
    RXYCODE_OPEN_PALETTE: "1",
    FORCE_COLOR: "1",
    TERM: "xterm-256color",
  },
  ...(process.platform === "win32" ? { useConpty } : {}),
});
pty.onData((d) => {
  buf += d;
});
pty.onExit((e) => {
  alive = false;
  exitInfo = e;
});
const t0 = Date.now();
while (Date.now() - t0 < 12000) {
  if (/命令/.test(plain(buf))) break;
  if (!alive) break;
  await sleep(200);
}
console.log("useConpty", useConpty, "palette", /命令/.test(plain(buf)), "alive", alive, "exit", exitInfo);
await sleep(500);
for (const ch of "model") {
  if (!alive) {
    console.log("dead before write", ch);
    break;
  }
  try {
    pty.write(ch);
    console.log("wrote", ch);
  } catch (e) {
    console.log("write fail", ch, e.message, "alive", alive, "exit", exitInfo);
    break;
  }
  await sleep(200);
}
await sleep(1500);
const p = plain(buf);
console.log("aliveAfter", alive, "exit", exitInfo);
console.log("stillFull32", /32\/32/.test(p));
console.log("filtered", (p.match(/\d+\/32/g) || []).slice(-6));
console.log("searchBits", (p.match(/搜索[^│]{0,30}|model[^│]{0,20}/g) || []).slice(-8));
try {
  pty.kill();
} catch {
  /* */
}
server.close();
process.exit(0);
