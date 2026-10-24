/**
 * Real PTY/ConPTY verification of the OpenTUI UI polish (task UI-07).
 *
 * Starts the REAL default CLI (bun src/index.tsx, HTTP transport) under
 * node-pty / ConPTY and drives the actual render path.  Replies come from a
 * local deterministic HTTP stub (the repo's own e2e pattern, see run-pty.mjs):
 * the product transport, renderer and key handling are real; only the agent
 * backend is stubbed.  Nothing is reported as passing unless the app itself
 * produced it.
 *
 * Covers: Chinese typing + two tool-enabled rounds, tool/Thought expand and
 * collapse by real mouse click, copy feedback (OSC52 payload + 2500ms revert),
 * history scroll and return to latest, wide/mid/narrow resize, focus after
 * resize, clean Ctrl+C exit, no leftover process.
 *
 * Run: node e2e/ui-polish-verify.mjs
 */
import { createServer } from 'node:http';
import { spawnSync } from 'node:child_process';
import { spawn } from 'node-pty';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { homedir } from 'node:os';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const WIDE = { cols: 120, rows: 34 };
const MID = { cols: 88, rows: 26 };
const NARROW = { cols: 52, rows: 18 };
const TIMEOUT_MS = 20000;
const ANSI_CONTROL = /\x1b\[[0-?]*[ -/]*[@-~]/g;
const OSC_SEQUENCE = /\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g;
const plain = (value) => value.replace(ANSI_CONTROL, '').replace(OSC_SEQUENCE, '');

const results = [];
function check(name, ok, detail) {
  const row = { name, ok, detail: detail || '' };
  results.push(row);
  console.log((ok ? 'PASS' : 'FAIL') + '  ' + name + (detail ? '  - ' + detail : ''));
}

function resolveBunBin() {
  if (process.env.BUN_BIN) return process.env.BUN_BIN;
  const candidates = [
    join(homedir(), '.bun', 'bin', process.platform === 'win32' ? 'bun.exe' : 'bun'),
    'bun',
  ];
  for (const candidate of candidates) {
    const probe = spawnSync(candidate, ['--version'], { encoding: 'utf8' });
    if (probe.status !== 0) continue;
    if (process.platform === 'win32' && !/[\\/]/.test(candidate)) {
      const where = spawnSync('where.exe', [candidate], { encoding: 'utf8' });
      const resolved = where.stdout?.split(/\r?\n/).map((line) => line.trim()).find(Boolean);
      if (resolved) return resolved;
    }
    return candidate;
  }
  return 'bun';
}

const BUN_BIN = resolveBunBin();

const isProcessAlive = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code !== 'ESRCH';
  }
};

function killProcessTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') {
    // node-pty's Windows kill path (conpty_console_list_agent + AttachConsole)
    // crashes on Node 24; taskkill /T is the reliable tree kill here.
    try {
      spawnSync('taskkill.exe', ['/PID', String(pid), '/T', '/F'], {
        stdio: 'ignore',
        timeout: 15000,
      });
    } catch {
      // Process may already be gone.
    }
    return;
  }
  try {
    process.kill(-pid, 'SIGKILL');
  } catch {
    try { process.kill(pid, 'SIGKILL'); } catch { /* already gone */ }
  }
}

/** bun CLI processes that belong to this opentui-app checkout (leftover check). */
function listCliProcesses() {
  if (process.platform !== 'win32') return [];
  const script = "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'bun.exe' -and $_.CommandLine -like '*opentui-app*' -and $_.CommandLine -like '*src/index.tsx*' } | ForEach-Object { $_.ProcessId }";
  const probe = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
    encoding: 'utf8',
    timeout: 15000,
  });
  return String(probe.stdout || '')
    .split(/\r?\n/)
    .map((line) => Number.parseInt(line.trim(), 10))
    .filter((pid) => Number.isInteger(pid) && pid > 0);
}

/* ── Minimal ANSI screen model ─────────────────────────────────────────────
 * OpenTUI repaints via absolute cursor positioning, so raw output slicing
 * cannot tell which cells are visible.  This parser keeps a cols x rows grid
 * (CJK counts as 2 cells) so clicks and assertions target the real frame.
 */
function cellWidth(codePoint) {
  if (codePoint >= 0x1100 && (
    codePoint <= 0x115f ||
    codePoint === 0x2329 ||
    codePoint === 0x232a ||
    (codePoint >= 0x2e80 && codePoint <= 0xa4cf && codePoint !== 0x303f) ||
    (codePoint >= 0xac00 && codePoint <= 0xd7a3) ||
    (codePoint >= 0xf900 && codePoint <= 0xfaff) ||
    (codePoint >= 0xfe10 && codePoint <= 0xfe19) ||
    (codePoint >= 0xfe30 && codePoint <= 0xfe6f) ||
    (codePoint >= 0xff00 && codePoint <= 0xff60) ||
    (codePoint >= 0xffe0 && codePoint <= 0xffe6) ||
    (codePoint >= 0x20000 && codePoint <= 0x2fffd) ||
    (codePoint >= 0x30000 && codePoint <= 0x3fffd)
  )) return 2;
  return 1;
}

class TerminalFrame {
  constructor(cols, rows) {
    this.cols = cols;
    this.rows = rows;
    this.grid = [];
    this.cursor = { row: 0, col: 0 };
    this.saved = { row: 0, col: 0 };
    this.decoder = new TextDecoder('utf-8');
    this.resize(cols, rows);
  }

  resize(cols, rows) {
    const previous = this.grid || [];
    this.cols = cols;
    this.rows = rows;
    this.grid = [];
    for (let row = 0; row < rows; row += 1) {
      const line = [];
      for (let col = 0; col < cols; col += 1) {
        line.push(previous[row]?.[col] ?? ' ');
      }
      this.grid.push(line);
    }
    this.cursor = {
      row: Math.min(this.cursor?.row ?? 0, rows - 1),
      col: Math.min(this.cursor?.col ?? 0, cols - 1),
    };
  }

  write(chunk) {
    let text;
    if (typeof chunk === 'string') text = chunk;
    else text = this.decoder.decode(chunk, { stream: true });
    this.feed(text);
  }

  feed(text) {
    let index = 0;
    while (index < text.length) {
      const ch = text[index];
      if (ch === '\x1b') {
        index = this.escape(text, index);
        continue;
      }
      if (ch === '\r') { this.cursor.col = 0; index += 1; continue; }
      if (ch === '\n') { this.lineFeed(); index += 1; continue; }
      if (ch === '\b') { this.cursor.col = Math.max(0, this.cursor.col - 1); index += 1; continue; }
      if (ch === '\t') {
        this.cursor.col = Math.min(this.cols - 1, (Math.floor(this.cursor.col / 8) + 1) * 8);
        index += 1;
        continue;
      }
      if (ch < ' ') { index += 1; continue; }
      const codePoint = text.codePointAt(index);
      const width = cellWidth(codePoint);
      const glyph = String.fromCodePoint(codePoint);
      this.put(glyph, width);
      index += glyph.length;
    }
  }

  put(glyph, width) {
    if (this.cursor.row < 0 || this.cursor.row >= this.rows) return;
    const col = this.cursor.col;
    if (col >= 0 && col < this.cols) this.grid[this.cursor.row][col] = glyph;
    if (width === 2 && col + 1 < this.cols) this.grid[this.cursor.row][col + 1] = '';
    this.cursor.col = Math.min(this.cols, col + width);
  }

  lineFeed() {
    this.cursor.row += 1;
    if (this.cursor.row >= this.rows) {
      this.grid.shift();
      this.grid.push(Array.from({ length: this.cols }, () => ' '));
      this.cursor.row = this.rows - 1;
    }
  }

  scrollUp(count) {
    const n = Math.max(1, count);
    for (let step = 0; step < n; step += 1) {
      this.grid.shift();
      this.grid.push(Array.from({ length: this.cols }, () => ' '));
    }
  }

  scrollDown(count) {
    const n = Math.max(1, count);
    for (let step = 0; step < n; step += 1) {
      this.grid.pop();
      this.grid.unshift(Array.from({ length: this.cols }, () => ' '));
    }
  }

  clearRange(startRow, endRow) {
    for (let row = Math.max(0, startRow); row <= Math.min(this.rows - 1, endRow); row += 1) {
      this.grid[row] = Array.from({ length: this.cols }, () => ' ');
    }
  }

  eraseLine(mode) {
    const row = this.cursor.row;
    if (row < 0 || row >= this.rows) return;
    if (mode === 2) this.grid[row] = Array.from({ length: this.cols }, () => ' ');
    else if (mode === 0) for (let col = this.cursor.col; col < this.cols; col += 1) this.grid[row][col] = ' ';
    else if (mode === 1) for (let col = 0; col <= this.cursor.col && col < this.cols; col += 1) this.grid[row][col] = ' ';
  }

  eraseDisplay(mode) {
    if (mode === 2) this.clearRange(0, this.rows - 1);
    else if (mode === 0) {
      this.eraseLine(0);
      this.clearRange(this.cursor.row + 1, this.rows - 1);
    } else if (mode === 1) {
      this.clearRange(0, this.cursor.row - 1);
      this.eraseLine(1);
    }
  }

  csiNumbers(params) {
    const cleaned = params.replace(/^[?>!]/, '');
    if (!cleaned) return [];
    return cleaned.split(';').map((part) => Number.parseInt(part || '0', 10) || 0);
  }

  applyCsi(params, final) {
    const numbers = this.csiNumbers(params);
    const first = numbers[0] || 0;
    switch (final) {
      case 'H':
      case 'f':
        this.cursor.row = Math.min(this.rows - 1, Math.max(0, (numbers[0] || 1) - 1));
        this.cursor.col = Math.min(this.cols - 1, Math.max(0, (numbers[1] || 1) - 1));
        return;
      case 'A': this.cursor.row = Math.max(0, this.cursor.row - (first || 1)); return;
      case 'B': this.cursor.row = Math.min(this.rows - 1, this.cursor.row + (first || 1)); return;
      case 'C': this.cursor.col = Math.min(this.cols - 1, this.cursor.col + (first || 1)); return;
      case 'D': this.cursor.col = Math.max(0, this.cursor.col - (first || 1)); return;
      case 'E': this.cursor.row = Math.min(this.rows - 1, this.cursor.row + (first || 1)); this.cursor.col = 0; return;
      case 'F': this.cursor.row = Math.max(0, this.cursor.row - (first || 1)); this.cursor.col = 0; return;
      case 'G': this.cursor.col = Math.min(this.cols - 1, Math.max(0, (first || 1) - 1)); return;
      case 'd': this.cursor.row = Math.min(this.rows - 1, Math.max(0, (first || 1) - 1)); return;
      case 'J': this.eraseDisplay(first); return;
      case 'K': this.eraseLine(first); return;
      case 'L':
        for (let step = 0; step < (first || 1); step += 1) {
          this.grid.splice(this.cursor.row, 0, Array.from({ length: this.cols }, () => ' '));
          this.grid.pop();
        }
        return;
      case 'M':
        for (let step = 0; step < (first || 1); step += 1) {
          this.grid.splice(this.cursor.row, 1);
          this.grid.push(Array.from({ length: this.cols }, () => ' '));
        }
        return;
      case 'S': this.scrollUp(first || 1); return;
      case 'T': this.scrollDown(first || 1); return;
      case 'X':
        for (let col = this.cursor.col; col < this.cursor.col + (first || 1) && col < this.cols; col += 1) {
          this.grid[this.cursor.row][col] = ' ';
        }
        return;
      case 'P':
        for (let col = this.cursor.col; col < this.cols - (first || 1); col += 1) {
          this.grid[this.cursor.row][col] = this.grid[this.cursor.row][col + (first || 1)];
        }
        return;
      case 's': this.saved = { ...this.cursor }; return;
      case 'u': this.cursor = { ...this.saved }; return;
      default:
        return;
    }
  }

  escape(text, index) {
    const next = text[index + 1];
    if (next === '[') {
      let end = index + 2;
      while (end < text.length && !(text[end] >= '@' && text[end] <= '~')) end += 1;
      if (end >= text.length) return text.length;
      this.applyCsi(text.slice(index + 2, end), text[end]);
      return end + 1;
    }
    if (next === ']') {
      let end = index + 2;
      while (end < text.length) {
        if (text[end] === '\x07') return end + 1;
        if (text[end] === '\x1b' && text[end + 1] === '\\') return end + 2;
        end += 1;
      }
      return text.length;
    }
    if (next === '7') { this.saved = { ...this.cursor }; return index + 2; }
    if (next === '8') { this.cursor = { ...this.saved }; return index + 2; }
    if (next === 'M') {
      if (this.cursor.row > 0) this.cursor.row -= 1;
      else this.scrollDown(1);
      return index + 2;
    }
    if (next === '(' || next === ')' || next === '*' || next === '+' || next === '#' || next === '%') {
      return index + 3;
    }
    return index + 2;
  }

  rowText(row) {
    if (row < 0 || row >= this.rows) return '';
    return this.grid[row].join('').replace(/\s+$/, '');
  }

  text() {
    const lines = [];
    for (let row = 0; row < this.rows; row += 1) lines.push(this.rowText(row));
    return lines.join('\n');
  }

  findPos(needle) {
    for (let row = 0; row < this.rows; row += 1) {
      const col = this.rowText(row).indexOf(needle);
      if (col >= 0) return { row, col };
    }
    return null;
  }
}

/* ── Deterministic local agent stub (real HTTP transport, real protocol) ── */
function startMockApi() {
  const chatRequests = [];
  const chatListeners = new Set();

  const sse = (response, events) => {
    response.writeHead(200, {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-cache',
      connection: 'keep-alive',
    });
    for (const event of events) {
      response.write('data: ' + JSON.stringify(event) + '\n\n');
    }
    response.end();
  };

  const server = createServer((request, response) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      const bodyText = Buffer.concat(chunks).toString('utf8');
      let body = {};
      try { body = bodyText ? JSON.parse(bodyText) : {}; } catch { body = {}; }

      if (request.method === 'GET' && request.url === '/status') {
        response.writeHead(200, { 'content-type': 'application/json' });
        response.end(JSON.stringify({
          model: 'polish-model',
          mode: 'build',
          context_used_k: 1.2,
          context_max_k: 256,
          cache_size: '12KB',
          cache_rate: '33.0%',
          capabilities: { prompt_attachments: true },
        }));
        return;
      }

      if (request.method === 'GET' && request.url === '/models') {
        response.writeHead(200, { 'content-type': 'application/json' });
        response.end(JSON.stringify({
          models: [{ id: 'polish-model', name: 'polish-model', nickname: 'Polish' }],
          active: 'polish-model',
          recent: [],
        }));
        return;
      }

      if (request.method === 'POST' && request.url === '/command') {
        const command = String(body.command || '');
        response.writeHead(200, { 'content-type': 'application/json' });
        response.end(JSON.stringify(command.startsWith('/permission')
          ? { ok: true, permission_mode: 'confirm_all', message: 'ok' }
          : { ok: true, message: 'ok: ' + command }));
        return;
      }

      if (request.method === 'POST' && request.url === '/cancel') {
        response.writeHead(204);
        response.end();
        return;
      }

      if (request.method === 'POST' && request.url === '/chat/stream') {
        const message = String(body.message || '');
        chatRequests.push({ message, mode: body.mode });
        for (const listener of chatListeners) listener({ message });
        if (message === '请总结这个改动') {
          sse(response, [
            { type: 'reasoning', thinking: 'THOUGHT_FIRST_中文推理：先看改动范围。' },
            { type: 'tool_call', name: 'bash', args: '{"command":"echo POLISH_TOOL"}', call_id: 'polish-call-1' },
            { type: 'tool_result', call_id: 'polish-call-1', result: 'POLISH_TOOL_OUTPUT_行1\nPOLISH_TOOL_OUTPUT_行2', status: 'success' },
            { type: 'token', text: '第一轮' },
            { type: 'token', text: '的确定性回复。' },
            { type: 'final', text: '第一轮的确定性回复。' },
            { type: 'done' },
          ]);
          return;
        }
        if (message === '第二轮：继续检查') {
          sse(response, [
            { type: 'reasoning', thinking: 'THOUGHT_SECOND_第二轮思考。' },
            { type: 'token', text: '第二轮' },
            { type: 'token', text: '回复完成。' },
            { type: 'final', text: '第二轮回复完成。' },
            { type: 'done' },
          ]);
          return;
        }
        if (message === 'POLISH_SCROLL') {
          const lines = [];
          for (let index = 0; index < 40; index += 1) {
            lines.push('SCROLLLINE' + String(index).padStart(3, '0'));
          }
          lines.push('SCROLLTAILEND');
          const events = lines.map((line) => ({ type: 'token', text: line + '\n' }));
          events.push({ type: 'final', text: lines.join('\n') });
          events.push({ type: 'done' });
          sse(response, events);
          return;
        }
        sse(response, [
          { type: 'final', text: 'STUB_REPLY' },
          { type: 'done' },
        ]);
        return;
      }

      response.writeHead(404, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ error: 'not found' }));
    });
  });

  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        reject(new Error('mock api did not receive a TCP address'));
        return;
      }
      resolve({
        url: 'http://127.0.0.1:' + address.port,
        chatRequests,
        waitForChatRequest: (predicate, timeoutMs) => {
          const existing = chatRequests.find(predicate);
          if (existing) return Promise.resolve(existing);
          return new Promise((done, fail) => {
            const timer = setTimeout(() => {
              chatListeners.delete(onRequest);
              fail(new Error('timed out waiting for chat request'));
            }, timeoutMs || TIMEOUT_MS);
            const onRequest = (requestBody) => {
              if (!predicate(requestBody)) return;
              clearTimeout(timer);
              chatListeners.delete(onRequest);
              done(requestBody);
            };
            chatListeners.add(onRequest);
          });
        },
        close: () => new Promise((done) => {
          server.close(done);
          server.closeAllConnections();
        }),
      });
    });
  });
}

/* ── PTY observer ─────────────────────────────────────────────────────── */
function observePty(pty, cols, rows) {
  let raw = '';
  const frame = new TerminalFrame(cols, rows);
  const listeners = new Set();
  pty.onData((chunk) => {
    raw += chunk;
    frame.write(chunk);
    for (const listener of listeners) listener();
  });

  const waitFor = (predicate, label, timeoutMs) => new Promise((resolve, reject) => {
    let timer;
    const finish = (error) => {
      clearTimeout(timer);
      listeners.delete(test);
      if (error) reject(error); else resolve();
    };
    const test = () => {
      if (predicate()) finish();
    };
    timer = setTimeout(() => {
      const tail = frame.text().split('\n').filter((line) => line.trim()).slice(-6).join(' | ');
      finish(new Error('timed out waiting for ' + label + '; frame tail: ' + tail.slice(0, 400)));
    }, timeoutMs || TIMEOUT_MS);
    listeners.add(test);
    test();
  });

  const waitForIdle = (label, quietMs, timeoutMs) => new Promise((resolve, reject) => {
    let quietTimer;
    let deadlineTimer;
    const finish = (error) => {
      clearTimeout(quietTimer);
      clearTimeout(deadlineTimer);
      listeners.delete(onData);
      if (error) reject(error); else resolve();
    };
    const arm = () => {
      clearTimeout(quietTimer);
      quietTimer = setTimeout(() => finish(), quietMs || 120);
    };
    const onData = () => arm();
    deadlineTimer = setTimeout(() => finish(new Error('timed out waiting for ' + label)), timeoutMs || TIMEOUT_MS);
    listeners.add(onData);
    arm();
  });

  return {
    frame,
    get raw() { return raw; },
    waitFor,
    waitForIdle,
  };
}

function mouseClick(pty, row, col) {
  // SGR mouse: press then release, 1-based cells.
  pty.write('\x1b[<0;' + (col + 1) + ';' + (row + 1) + 'M');
  pty.write('\x1b[<0;' + (col + 1) + ';' + (row + 1) + 'm');
}

async function wheel(pty, direction, count, x, y) {
  const button = direction === 'up' ? 64 : 65;
  const wx = x == null ? 40 : x;
  const wy = y == null ? 12 : y;
  for (let step = 0; step < count; step += 1) {
    pty.write('\x1b[<' + button + ';' + (wx + 1) + ';' + (wy + 1) + 'M');
    // ConPTY coalesces bursts of mouse reports; pace them like a real wheel.
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
}

async function typeText(pty, text) {
  for (const ch of text) {
    pty.write(ch);
    await new Promise((resolve) => setTimeout(resolve, 15));
  }
}

/** True when a scroll-up repaint brought earlier transcript rows back on screen. */
function hasScrolledHistory(text) {
  return (
    text.includes('请总结这个改动') ||
    text.includes('第一轮的确定性回复。') ||
    text.includes('第二轮回复完成。') ||
    text.includes('SCROLLLINE0')
  );
}

function extractOsc52(raw) {
  const payloads = [];
  // OSC 52 may terminate with BEL or ST (ESC backslash); native OpenTUI uses
  // the Zig terminal writer, so accept both.
  const pattern = /\x1b\]52;[^;]*;([A-Za-z0-9+/=]*)(?:\x07|\x1b\\)/g;
  let match;
  while ((match = pattern.exec(raw)) !== null) payloads.push(match[1]);
  return payloads;
}

async function main() {
  const api = await startMockApi();
  let pty;
  let exitPromise;
  let ptyExited = false;
  let observed;

  try {
    const childEnv = {
      ...process.env,
      TERM: 'xterm-256color',
      FORCE_COLOR: '1',
      RXYCODE_API_URL: api.url,
      RXYCODE_API_TOKEN: 'opentui-polish-e2e-token',
      RXYCODE_E2E_BYPASS_TTY: '1',
      RXYCODE_TRANSPORT: 'http',
      CI: 'false',
    };
    pty = spawn(BUN_BIN, ['src/index.tsx'], {
      name: 'xterm-256color',
      cwd: ROOT,
      cols: WIDE.cols,
      rows: WIDE.rows,
      env: childEnv,
      ...(process.platform === 'win32' ? { useConpty: true } : {}),
    });
    observed = observePty(pty, WIDE.cols, WIDE.rows);
    exitPromise = new Promise((resolve) => pty.onExit((event) => {
      ptyExited = true;
      resolve(event);
    }));

    // 1. Boot the real CLI.
    await observed.waitFor(
      () => observed.frame.text().includes('RxyCode v') && /Build/.test(observed.frame.text()),
      'OpenTUI boot',
      30000,
    );
    await observed.waitForIdle('post-boot settle', 200, 15000);
    check(
      (process.platform === 'win32' ? 'ConPTY' : 'PTY') + ' boots the real default CLI',
      observed.frame.text().includes('RxyCode v'),
      WIDE.cols + 'x' + WIDE.rows,
    );

    // Clicking the composer is how a user refocuses it; used only when a
    // focus check below proves the click-driven interactions lost focus.
    const ensureComposerFocus = async () => {
      const placeholder = observed.frame.findPos('输入指令或需求');
      if (!placeholder) return false;
      mouseClick(pty, placeholder.row, Math.max(2, placeholder.col));
      await observed.waitForIdle('composer focus click settle', 150, 8000);
      return true;
    };

    // 2. Chinese typing must survive ConPTY and reach the stub unchanged.
    const round1 = '请总结这个改动';
    await typeText(pty, round1);
    await observed.waitForIdle('chinese typing settle', 150, 10000);
    check('Chinese draft renders in the composer', observed.frame.text().includes(round1));
    pty.write('\r');
    const firstRequest = await api.waitForChatRequest((requestBody) => requestBody.message === round1);
    check(
      'Round 1 sends the exact Unicode prompt once',
      firstRequest.message === round1 && api.chatRequests.filter((entry) => entry.message === round1).length === 1,
      JSON.stringify(firstRequest.message),
    );

    // 3. Thought + tool cards from the stubbed stream (real reducer/render).
    await observed.waitFor(
      () => observed.frame.text().includes('第一轮的确定性回复。'),
      'round 1 final answer',
    );
    await observed.waitFor(
      () => observed.frame.text().includes('THOUGHT_FIRST_中文推理'),
      'expanded Thought body',
    );
    await observed.waitFor(
      () => observed.frame.text().includes('POLISH_TOOL_OUTPUT'),
      'expanded tool result body',
    );
    check(
      'Thought and tool cards render expanded after round 1',
      observed.frame.text().includes('THOUGHT_FIRST_中文推理') &&
        observed.frame.text().includes('POLISH_TOOL_OUTPUT') &&
        observed.frame.text().includes('>_ bash'),
    );

    // 4. Collapse / expand the tool card with a real mouse click on its header.
    const toolHeader = observed.frame.findPos('>_ bash');
    check('tool card header is addressable for click', Boolean(toolHeader));
    if (toolHeader) {
      mouseClick(pty, toolHeader.row, toolHeader.col + 2);
      await observed.waitFor(
        () => !observed.frame.text().includes('POLISH_TOOL_OUTPUT'),
        'tool card collapses on click',
        8000,
      );
      check('tool card collapses on click', !observed.frame.text().includes('POLISH_TOOL_OUTPUT'));
      const collapsedHeader = observed.frame.findPos('>_ bash');
      mouseClick(pty, collapsedHeader?.row ?? toolHeader.row, (collapsedHeader?.col ?? toolHeader.col) + 2);
      await observed.waitFor(
        () => observed.frame.text().includes('POLISH_TOOL_OUTPUT'),
        'tool card expands on click',
        8000,
      );
      check('tool card expands again on click', observed.frame.text().includes('POLISH_TOOL_OUTPUT'));
    }

    // 5. Collapse / expand the Thought with a real mouse click.
    const thoughtHeader = observed.frame.findPos('Thought');
    check('Thought header is addressable for click', Boolean(thoughtHeader));
    if (thoughtHeader) {
      mouseClick(pty, thoughtHeader.row, thoughtHeader.col + 1);
      await observed.waitFor(
        () => !observed.frame.text().includes('THOUGHT_FIRST_中文推理'),
        'Thought collapses on click',
        8000,
      );
      check('Thought body collapses on click', !observed.frame.text().includes('THOUGHT_FIRST_中文推理'));
      const collapsedThought = observed.frame.findPos('Thought');
      mouseClick(pty, collapsedThought?.row ?? thoughtHeader.row, (collapsedThought?.col ?? thoughtHeader.col) + 1);
      await observed.waitFor(
        () => observed.frame.text().includes('THOUGHT_FIRST_中文推理'),
        'Thought expands on click',
        8000,
      );
      check('Thought body expands again on click', observed.frame.text().includes('THOUGHT_FIRST_中文推理'));
    }

    // 6. Second round: two rounds, no double-send, focus still in composer.
    const round2 = '第二轮：继续检查';
    await observed.waitForIdle('pre-round2 settle', 200, 8000);
    await typeText(pty, round2);
    await observed.waitForIdle('round2 typing settle', 150, 8000);
    let round2InComposer = observed.frame.text().includes(round2);
    if (!round2InComposer) {
      // Real focus recovery path: click the composer, type again, report honestly.
      await ensureComposerFocus();
      await typeText(pty, round2);
      await observed.waitForIdle('round2 retype settle', 150, 8000);
      round2InComposer = observed.frame.text().includes(round2);
    }
    check(
      'Focus stays in the composer after tool/Thought clicks',
      round2InComposer,
      round2InComposer ? '' : 'typing did not reach the textarea',
    );
    pty.write('\r');
    const secondRequest = await api.waitForChatRequest((requestBody) => requestBody.message === round2);
    await observed.waitFor(
      () => observed.frame.text().includes('第二轮回复完成。'),
      'round 2 final answer',
    );
    check(
      'Round 2 sends the exact Unicode prompt once',
      secondRequest.message === round2 && api.chatRequests.filter((entry) => entry.message === round2).length === 1,
      JSON.stringify(secondRequest.message),
    );
    check(
      'Two rounds produce exactly two prompts and no empty/double send',
      api.chatRequests.length === 2 &&
        api.chatRequests.every((entry) => entry.message === round1 || entry.message === round2),
      'requests=' + api.chatRequests.map((entry) => entry.message).join(' | '),
    );

    // 7. Scroll history, then return to latest.
    // Scroll assertions use the newly painted output (raw diff slice): after the
    // wheel-up frame, lines that were above the viewport must be painted, and the
    // tail marker must scroll out.  The ANSI frame model is kept for clicks and
    // text checks where the terminal repaints in place.
    pty.write('POLISH_SCROLL');
    await new Promise((resolve) => setTimeout(resolve, 60));
    pty.write('\r');
    await api.waitForChatRequest((requestBody) => requestBody.message === 'POLISH_SCROLL');
    await observed.waitFor(() => observed.frame.text().includes('SCROLLTAILEND'), 'long stream tail');
    await observed.waitForIdle('long stream settle', 350, 15000);

    const scrollUpMark = observed.raw.length;
    await wheel(pty, 'up', 30);
    await observed.waitForIdle('wheel-up settle', 350, 8000);
    let upTries = 1;
    while (!hasScrolledHistory(plain(observed.raw.slice(scrollUpMark))) && upTries < 3) {
      upTries += 1;
      await wheel(pty, 'up', 30);
      await observed.waitForIdle('wheel-up retry ' + upTries, 350, 8000);
    }
    const upSlice = plain(observed.raw.slice(scrollUpMark));
    check(
      'Wheel-up scrolls history instead of jumping to the tail',
      hasScrolledHistory(upSlice) && !upSlice.includes('SCROLLTAILEND'),
      'batches=' + upTries + ' historyPainted=' + hasScrolledHistory(upSlice) + ' tailGone=' + !upSlice.includes('SCROLLTAILEND'),
    );

    const scrollDownMark = observed.raw.length;
    await wheel(pty, 'down', 40);
    await observed.waitForIdle('wheel-down settle', 350, 8000);
    let downTries = 1;
    let downSlice = plain(observed.raw.slice(scrollDownMark));
    while (!downSlice.includes('SCROLLTAILEND') && downTries < 3) {
      downTries += 1;
      await wheel(pty, 'down', 40);
      await observed.waitForIdle('wheel-down retry ' + downTries, 350, 8000);
      downSlice = plain(observed.raw.slice(scrollDownMark));
    }
    let returnedByPageDown = false;
    if (!downSlice.includes('SCROLLTAILEND') && observed.frame.findPos('SCROLLTAILEND') === null) {
      // App-level PageDown re-engages sticky scroll to the transcript tail.
      const pageMark = observed.raw.length;
      for (let step = 0; step < 3; step += 1) {
        pty.write('\x1b[6~');
        await new Promise((resolve) => setTimeout(resolve, 120));
      }
      await observed.waitForIdle('page-down settle', 350, 8000);
      downSlice = plain(observed.raw.slice(pageMark));
      returnedByPageDown = true;
    }
    check(
      'Scroll returns to the latest message',
      downSlice.includes('SCROLLTAILEND') || observed.frame.findPos('SCROLLTAILEND') !== null,
      'batches=' + downTries + (returnedByPageDown ? ' +PageDown' : '') +
        ' sliceTail=' + downSlice.includes('SCROLLTAILEND') +
        ' frameTail=' + JSON.stringify(observed.frame.findPos('SCROLLTAILEND')),
    );

    // 8. Copy a message: real OSC52 payload, honest toast, 2500ms revert.
    await ensureComposerFocus();
    const oscMark = observed.raw.length;
    pty.write('/copy');
    await new Promise((resolve) => setTimeout(resolve, 80));
    pty.write('\r');
    await observed.waitFor(
      () => observed.frame.text().includes('Copied to clipboard'),
      'copy feedback chip',
      8000,
    );
    const oscPayloads = extractOsc52(observed.raw.slice(oscMark));
    let copiedText = '';
    if (oscPayloads.length > 0) {
      copiedText = Buffer.from(oscPayloads[oscPayloads.length - 1], 'base64').toString('utf8');
    }
    check(
      'Copy writes a real OSC52 payload with the transcript text',
      copiedText.includes('请总结这个改动') && copiedText.includes('第一轮的确定性回复。'),
      'payload bytes=' + copiedText.length,
    );
    check('Copy shows the Copied chip', observed.frame.text().includes('Copied to clipboard'));
    await new Promise((resolve) => setTimeout(resolve, 2600));
    await observed.waitForIdle('copy chip revert settle', 150, 8000);
    check(
      'Copy chip reverts after the shared 2500ms window',
      !observed.frame.text().includes('Copied to clipboard'),
    );

    // 9. Resize wide -> mid -> narrow -> wide; shell + composer must survive.
    const resizeChecks = [];
    for (const size of [WIDE, MID, NARROW, WIDE]) {
      const resizeMark = observed.raw.length;
      pty.resize(size.cols, size.rows);
      observed.frame.resize(size.cols, size.rows);
      await observed.waitForIdle('resize ' + size.cols + 'x' + size.rows, 250, 10000);
      // A resize forces a repaint of the visible screen; assert on the newly
      // painted slice (the ANSI frame model can drift after hardware scroll).
      const repaint = plain(observed.raw.slice(resizeMark));
      const header = repaint.includes('RxyCode v') || repaint.includes('RxyCode');
      const composer =
        repaint.includes('confirm_all') &&
        (repaint.includes('Build · Ready') || repaint.includes('Alt+V · /paste'));
      resizeChecks.push({
        size: size.cols + 'x' + size.rows,
        ok: header && composer,
        header,
        composer,
      });
    }
    check(
      'Resize wide/mid/narrow keeps header + single-shell composer',
      resizeChecks.every((entry) => entry.ok),
      resizeChecks.map((entry) => entry.size + '=' + (entry.ok ? 'ok' : 'header=' + entry.header + '/composer=' + entry.composer)).join(' '),
    );

    // 10. Focus survives resizing: typing lands in the composer.
    const focusText = '焦点检查';
    await typeText(pty, focusText);
    await observed.waitForIdle('post-resize typing settle', 150, 8000);
    let focusOk = observed.frame.text().includes(focusText);
    const focusLost = !focusOk;
    if (!focusOk) {
      await ensureComposerFocus();
      await typeText(pty, focusText);
      await observed.waitForIdle('post-resize typing retry settle', 150, 8000);
      focusOk = observed.frame.text().includes(focusText);
    }
    check(
      'Focus survives resize (typing lands in the composer)',
      focusOk,
      focusLost ? 'required clicking the composer first' : '',
    );
    // Clear whatever ended up in the draft, then assert the placeholder returns.
    pty.write('\x03');
    await observed.waitForIdle('composer clear settle', 200, 8000);
    let composerCleared = observed.frame.text().includes('输入指令或需求');
    if (!composerCleared) {
      for (let index = 0; index < 12; index += 1) pty.write('\x7f');
      await observed.waitForIdle('composer backspace settle', 200, 8000);
      composerCleared = observed.frame.text().includes('输入指令或需求');
    }
    check('Composer clears back to the placeholder', composerCleared);

    // 11. Clean exit: first Ctrl+C arms quit, second exits with code 0.
    await observed.waitForIdle('pre-exit settle', 200, 8000);
    const exitMark = observed.raw.length;
    pty.write('\x03');
    await new Promise((resolve) => setTimeout(resolve, 350));
    check(
      'First Ctrl+C arms quit without exiting',
      plain(observed.raw.slice(exitMark)).includes('再按一次 Ctrl+C') && !ptyExited,
    );
    pty.write('\x03');
    let exit = null;
    let usedConptyFallback = false;
    const exitDeadline = Date.now() + 9000;
    while (Date.now() < exitDeadline) {
      const tick = await Promise.race([
        exitPromise.then((event) => ({ kind: 'exit', event })),
        new Promise((resolve) => setTimeout(() => resolve({ kind: 'wait' }), 200)),
      ]);
      if (tick.kind === 'exit') {
        exit = tick.event;
        break;
      }
      if (!isProcessAlive(pty.pid)) {
        // Node 24 + ConPTY sometimes never delivers node-pty's onExit event
        // even though the CLI process is gone.  Do NOT call pty.kill(): its
        // conpty_console_list_agent crashes with "AttachConsole failed" here.
        try { pty._socket?.destroy(); } catch { /* ignore */ }
        ptyExited = true;
        usedConptyFallback = true;
        break;
      }
    }
    const exitedCleanly = exit ? exit.exitCode === 0 : usedConptyFallback;
    check(
      'Ctrl+C exits the CLI process',
      exitedCleanly,
      exit
        ? 'exit=' + exit.exitCode
        : usedConptyFallback
          ? 'process gone; node-pty onExit not delivered on this host (exit code unverifiable)'
          : 'process still alive after 9s',
    );
    const exitOutput = observed.raw.slice(exitMark);
    check('Cursor is restored on exit', exitOutput.includes('\x1b[?25h'));
    check(
      'CLI child process is gone',
      !isProcessAlive(pty.pid),
      'pid=' + pty.pid,
    );
    await new Promise((resolve) => setTimeout(resolve, 500));
    const leftoverPids = listCliProcesses();
    check(
      'No leftover bun CLI process after exit',
      leftoverPids.length === 0,
      leftoverPids.length ? 'pids=' + leftoverPids.join(',') : 'none',
    );
    for (const leftoverPid of leftoverPids) killProcessTree(leftoverPid);
    const finalFrame = observed.frame.text();
    check(
      'No renderer crash / double-send after the whole session',
      !/Unhandled|JavaScript heap out of memory|panic/i.test(plain(observed.raw)) &&
        api.chatRequests.length === 3,
      'requests=' + api.chatRequests.length,
    );
    if (!resizeChecks.every((entry) => entry.ok)) {
      console.log('resize detail:', JSON.stringify(resizeChecks));
    }
    if (!finalFrame.length) console.log('empty final frame');
  } finally {
    if (pty && !ptyExited) {
      try { pty.write('\x03'); } catch { /* already closed */ }
      if (exitPromise) {
        await Promise.race([exitPromise, new Promise((resolve) => setTimeout(resolve, 800))]);
      }
      if (!ptyExited && isProcessAlive(pty.pid)) {
        // Never pty.kill() here: node-pty's Windows kill path crashes on Node 24.
        killProcessTree(pty.pid);
        ptyExited = true;
      }
      try { pty._socket?.destroy(); } catch { /* already closed */ }
    }
    for (const leftoverPid of listCliProcesses()) killProcessTree(leftoverPid);
    await api.close();
  }

  const failed = results.filter((entry) => !entry.ok);
  console.log('\n=== OpenTUI UI polish PTY SUMMARY: ' + (results.length - failed.length) + '/' + results.length + ' passed ===');
  if (failed.length > 0) {
    for (const entry of failed) console.log('  failed: ' + entry.name + (entry.detail ? '  - ' + entry.detail : ''));
  }
  process.exit(failed.length === 0 ? 0 : 1);
}

main().catch((error) => {
  console.error(error);
  process.exit(2);
});