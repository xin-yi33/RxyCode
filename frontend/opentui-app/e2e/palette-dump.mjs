/**
 * Dump OpenTUI command palette frame after Ctrl+P.
 * Asserts no category/command cell overlap (Skillsodel bug) and Chinese desc visible.
 */
import { createServer } from "node:http";
import { spawnSync } from "node:child_process";
import { spawn } from "node-pty";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { homedir } from "node:os";
import { writeFileSync } from "node:fs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

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
  return "bun";
}

const ANSI = /\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[PX^_].*?\x1b\\|\x1b./g;
const plain = (s) => s.replace(ANSI, "");

function startMockApi() {
  const server = createServer((req, res) => {
    if (req.method === "GET" && req.url === "/status") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(
        JSON.stringify({
          model: "pty-model",
          mode: "build",
          context_used_k: 1.2,
          context_max_k: 256,
          cache_size: "0B",
          cache_rate: "0%",
        }),
      );
      return;
    }
    res.writeHead(404);
    res.end();
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({ server, port });
    });
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const { server, port } = await startMockApi();
const bun = resolveBunBin();
let buf = "";

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
});

pty.onData((d) => {
  buf += d;
});

// Wait until palette shows grouped commands
for (let i = 0; i < 40; i++) {
  await sleep(250);
  if (plain(buf).includes("/clear") && plain(buf).includes("添加新模型")) break;
}
await sleep(400);

const text = plain(buf);
writeFileSync(join(ROOT, "e2e", "palette-dump.txt"), text, "utf8");

const checks = [
  ["title", /命令/],
  ["esc", /esc/i],
  ["search", /搜索/],
  ["category session", /会话/],
  ["category agent", /Agent/],
  ["clear name", /\/clear/],
  ["clear desc", /清除对话上下文/],
  ["addmodel name", /\/addmodel/],
  ["addmodel desc", /添加新模型/],
  ["no Skillsodel", { not: /Skillsodel/ }],
  ["no Agentskill", { not: /Agentskill/ }],
  ["no 系统ild", { not: /系统ild/ }],
  ["wheel hint", /滚轮滚动/],
];

let failed = 0;
for (const [name, rule] of checks) {
  let ok;
  if (rule instanceof RegExp) ok = rule.test(text);
  else ok = !rule.not.test(text);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failed += 1;
}

// Print a readable excerpt around command list
const lines = text.split(/\r?\n/).filter((l) => l.trim());
const hit = lines.findIndex((l) => l.includes("/addmodel") || l.includes("命令"));
const excerpt = lines.slice(Math.max(0, hit - 2), hit + 18).join("\n");
console.log("\n--- excerpt ---\n" + excerpt + "\n---------------\n");

pty.kill();
server.close();
process.exit(failed ? 1 : 0);
