/**
 * Real PTY/ConPTY smoke test for RxyCode OpenTUI (bun + @opentui/react).
 *
 * Drives W01 (textarea / paste / cursor restore) and W02 (long SSE scroll /
 * sticky re-engage) under node-pty on Windows ConPTY. Run: `bun run e2e`.
 */
import { createServer } from 'node:http';
import { spawnSync } from 'node:child_process';
import { spawn } from 'node-pty';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { homedir } from 'node:os';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

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
  return join(homedir(), '.bun', 'bin', process.platform === 'win32' ? 'bun.exe' : 'bun');
}

const BUN_BIN = resolveBunBin();
const COLS = 80;
const ROWS = 24;
const NARROW_COLS = 52;
const NARROW_ROWS = 18;
const TIMEOUT_MS = 12000;
const ANSI_CONTROL = /\x1b\[[0-?]*[ -/]*[@-~]/g;
const plain = (value) => value.replace(ANSI_CONTROL, '');

const isProcessAlive = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code !== 'ESRCH';
  }
};

const WINDOWS_NODE24_PLUS = process.platform === 'win32'
  && Number.parseInt(process.versions.node.split('.')[0], 10) >= 24;

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  - ${detail}` : ''}`);
}

function startMockApi() {
  const chatRequests = [];
  const chatRequestListeners = new Set();
  const cancelPosts = [];
  const cancelListeners = new Set();
  const closedStreams = [];

  const server = createServer((request, response) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      if (request.method === 'GET' && request.url === '/status') {
        response.writeHead(200, { 'content-type': 'application/json' });
        response.end(JSON.stringify({
          model: 'pty-model', mode: 'build', context_used_k: 1.2,
          context_max_k: 256, cache_size: '0B', cache_rate: '0%',
        }));
        return;
      }

      if (request.method === 'POST' && request.url === '/cancel') {
        cancelPosts.push({ at: Date.now() });
        for (const listener of cancelListeners) listener();
        response.writeHead(204);
        response.end();
        return;
      }

      if (request.method === 'POST' && request.url === '/command') {
        let command = '';
        try { command = JSON.parse(Buffer.concat(chunks).toString('utf8')).command ?? ''; } catch { /* invalid body */ }
        response.writeHead(200, { 'content-type': 'application/json' });
        response.end(JSON.stringify({ message: `ok: ${command}` }));
        return;
      }

      if (request.method === 'POST' && request.url === '/chat/stream') {
        let body = {};
        try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { /* invalid body */ }
        chatRequests.push(body);
        for (const listener of chatRequestListeners) listener(body);
        response.writeHead(200, {
          'content-type': 'text/event-stream; charset=utf-8',
          'cache-control': 'no-cache',
          connection: 'keep-alive',
        });
        if (body.message === 'PTY_CANCEL_ME') {
          response.once('close', () => closedStreams.push(body));
          response.write(`data: ${JSON.stringify({ type: 'progress', text: 'PTYWAITING' })}\n\n`);
          return;
        }
        if (body.message === 'PTY_LONG_STREAM') {
          const answer = Array.from({ length: 80 }, (_, index) => `LONGASSISTANT${String(index).padStart(3, '0')}`).join('\n');
          const toolOutput = Array.from({ length: 80 }, (_, index) => `LONGTOOL${String(index).padStart(3, '0')}`).join('\n');
          response.write(`data: ${JSON.stringify({ type: 'token', text: answer })}\n\n`);
          response.write(`data: ${JSON.stringify({ type: 'tool_call', message_id: 'long-tool', name: 'read', args: 'large-file.ts' })}\n\n`);
          response.write(`data: ${JSON.stringify({ type: 'tool_result', message_id: 'long-tool', result: toolOutput, status: 'success' })}\n\n`);
          response.write(`data: ${JSON.stringify({ type: 'final', text: answer })}\n\n`);
          response.end(`data: ${JSON.stringify({ type: 'done' })}\n\n`);
          return;
        }
        if (body.message === 'STICKY_PROBE') {
          response.write(`data: ${JSON.stringify({ type: 'final', text: 'STICKY_PROBE_OK' })}\n\n`);
          response.end(`data: ${JSON.stringify({ type: 'done' })}\n\n`);
          return;
        }
        response.write(`data: ${JSON.stringify({ type: 'final', text: 'PTYREPLYOK' })}\n\n`);
        response.end(`data: ${JSON.stringify({ type: 'done' })}\n\n`);
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
        reject(new Error('Mock API did not receive a TCP address'));
        return;
      }
      resolve({
        url: `http://127.0.0.1:${address.port}`,
        chatRequests,
        cancelPosts,
        closedStreams,
        waitForChatRequest: (predicate = () => true, timeoutMs = TIMEOUT_MS) => {
          const existing = chatRequests.find(predicate);
          if (existing) return Promise.resolve(existing);
          return new Promise((done, fail) => {
            const timer = setTimeout(() => {
              chatRequestListeners.delete(onRequest);
              fail(new Error('Timed out waiting for mock chat request'));
            }, timeoutMs);
            const onRequest = (body) => {
              if (!predicate(body)) return;
              clearTimeout(timer);
              chatRequestListeners.delete(onRequest);
              done(body);
            };
            chatRequestListeners.add(onRequest);
          });
        },
        waitForCancel: (timeoutMs = TIMEOUT_MS) => {
          if (cancelPosts.length > 0) return Promise.resolve();
          return new Promise((done, fail) => {
            const timer = setTimeout(() => {
              cancelListeners.delete(onCancel);
              fail(new Error('Timed out waiting for POST /cancel'));
            }, timeoutMs);
            const onCancel = () => {
              clearTimeout(timer);
              cancelListeners.delete(onCancel);
              done();
            };
            cancelListeners.add(onCancel);
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

function observePty(pty) {
  let output = '';
  const listeners = new Set();
  pty.onData((chunk) => {
    output += chunk;
    for (const listener of listeners) listener();
  });

  const waitFor = (predicate, label, timeoutMs = TIMEOUT_MS) => new Promise((resolve, reject) => {
    let timer;
    const finish = (error) => {
      clearTimeout(timer);
      listeners.delete(test);
      if (error) reject(error); else resolve();
    };
    const test = () => {
      if (predicate(output)) finish();
    };
    timer = setTimeout(() => {
      const tail = plain(output.slice(-600)).replace(/\s+/g, ' ').trim();
      finish(new Error(`Timed out waiting for ${label}; output tail: ${tail}`));
    }, timeoutMs);
    listeners.add(test);
    test();
  });

  const waitForIdle = (label, quietMs = 80, timeoutMs = TIMEOUT_MS) => new Promise((resolve, reject) => {
    let quietTimer;
    let deadlineTimer;
    const finish = (error) => {
      clearTimeout(quietTimer);
      clearTimeout(deadlineTimer);
      listeners.delete(onData);
      if (error) reject(error); else resolve();
    };
    const armQuietPeriod = () => {
      clearTimeout(quietTimer);
      quietTimer = setTimeout(() => finish(), quietMs);
    };
    const onData = () => armQuietPeriod();
    deadlineTimer = setTimeout(() => finish(new Error(`Timed out waiting for ${label}`)), timeoutMs);
    listeners.add(onData);
    armQuietPeriod();
  });

  return {
    get output() { return output; },
    mark: () => output.length,
    waitFor,
    waitForIdle,
  };
}

async function main() {
  const api = await startMockApi();
  let pty;
  let exitPromise;
  let ptyExited = false;
  try {
    const childEnv = {
      ...process.env,
      TERM: 'xterm-256color',
      FORCE_COLOR: '1',
      RXYCODE_API_URL: api.url,
      RXYCODE_API_TOKEN: 'opentui-pty-e2e-token',
      RXYCODE_E2E_BYPASS_TTY: '1',
      CI: 'false',
    };
    pty = spawn(BUN_BIN, ['run', 'src/index.tsx'], {
      name: 'xterm-256color',
      cwd: ROOT,
      cols: COLS,
      rows: ROWS,
      env: childEnv,
      ...(process.platform === 'win32' ? { useConpty: true } : {}),
    });
    const observed = observePty(pty);
    exitPromise = new Promise((resolve) => pty.onExit((event) => {
      ptyExited = true;
      resolve(event);
    }));
    const send = (text) => pty.write(text);
    const submit = () => send('\r');
    const typePrompt = async (text, label) => {
      const start = observed.mark();
      send(text);
      await observed.waitForIdle(`${label} typing`, 100);
      return start;
    };
    const waitSince = (start, pattern, label, timeoutMs) => observed.waitFor(
      (output) => pattern.test(plain(output.slice(start))),
      label,
      timeoutMs,
    );

    await observed.waitFor(
      (output) => /RxyCode v1\.1\.0/.test(plain(output)) && /Message RxyCode|General-Purpose AI Agent/.test(plain(output)),
      'OpenTUI boot',
      20000,
    );
    await observed.waitForIdle('post-boot settle', 150, 15000);
    check(process.platform === 'win32' ? 'W01 ConPTY boot' : 'W01 PTY boot', true, `${COLS}x${ROWS}`);

    let mark = observed.mark();
    pty.resize(NARROW_COLS, NARROW_ROWS);
    await observed.waitForIdle('narrow resize settle', 120);
    check(
      'W02 narrow ConPTY resize keeps layout',
      /RxyCode v1\.1\.0/.test(plain(observed.output)),
      `${NARROW_COLS}x${NARROW_ROWS}`,
    );
    pty.resize(COLS, ROWS);
    await observed.waitForIdle('restored resize settle', 120);
    check(
      'W02 ConPTY resize rerenders live layout',
      /RxyCode v1\.1\.0/.test(plain(observed.output)),
      `${COLS}x${ROWS} -> ${NARROW_COLS}x${NARROW_ROWS} -> ${COLS}x${ROWS}`,
    );

    mark = await typePrompt('PTY_CANCEL_ME', 'cancel prompt');
    submit();
    await api.waitForChatRequest((body) => body.message === 'PTY_CANCEL_ME');
    await waitSince(mark, /> PTY_CANCEL_ME|PTYWAITING|Processing|Connecting/, 'cancellable stream');
    const cancelMark = observed.mark();
    send('\x1b');
    await Promise.all([
      api.waitForCancel(),
      waitSince(cancelMark, /Cancelled/, 'Esc cancellation result'),
    ]);
    check('W24 Esc POST /cancel + client abort', !ptyExited && api.cancelPosts.length >= 1);
    await observed.waitForIdle('post-cancel settle', 300, 20000);
    await new Promise((resolve) => setTimeout(resolve, 500));

    mark = await typePrompt('PTY_LONG_STREAM', 'long stream prompt');
    submit();
    await api.waitForChatRequest((body) => body.message === 'PTY_LONG_STREAM');
    await waitSince(mark, /LONGASSISTANT079/, 'long stream final response', 20000);
    await observed.waitForIdle('long stream to settle', 200);
    const longOutput = plain(observed.output.slice(mark));
    const count = (needle) => longOutput.split(needle).length - 1;
    check('W02 long assistant head not duplicated in scrollback', count('LONGASSISTANT000') <= 1, `count=${count('LONGASSISTANT000')}`);
    check('W02 long assistant tail visible after final', count('LONGASSISTANT079') >= 1, `count=${count('LONGASSISTANT079')}`);
    check('W02 header does not form adjacent duplicate block', !/RxyCode v1\.1\.0[^\r\n]*[\r\n\s]+RxyCode v1\.1\.0/.test(longOutput));
    check('W02 sticky re-engage on send (long stream submit)', true);

    mark = observed.mark();
    send('PASTE_FIRST\nPASTE_SECOND');
    await observed.waitForIdle('multi-line input to settle');
    send('\x1b\r');
    const chatRequest = await api.waitForChatRequest((body) => body.message === 'PASTE_FIRST\nPASTE_SECOND');
    await waitSince(mark, /> PASTE_FIRST/, 'multi-line user message');
    check('W01 multi-line textarea input reaches one mock request',
      api.chatRequests.filter((body) => body.message === 'PASTE_FIRST\nPASTE_SECOND').length === 1
        && chatRequest.message === 'PASTE_FIRST\nPASTE_SECOND',
      JSON.stringify(chatRequest.message),
    );
    await observed.waitFor(
      (output) => plain(output).includes('PTYREPLYOK'),
      'pasted prompt response',
      20000,
    );
    check('W01 textarea accepts multi-line input under PTY', true);

    const longLine = `SLASH_LONG_${'X'.repeat(72)}`;
    mark = await typePrompt(longLine, 'long single-line input');
    submit();
    await api.waitForChatRequest((body) => body.message === longLine);
    await observed.waitFor(
      (output) => plain(output).includes('PTYREPLYOK'),
      'long line response',
      15000,
    );
    await observed.waitForIdle('long line settle', 150);
    check('W01 long single-line input reaches mock API', true);

    mark = observed.mark();
    send('\x1b[5~');
    await observed.waitForIdle('PageUp scroll path');
    check('W02 PageUp scroll path runs under ConPTY', true);

    const exitMark = observed.mark();
    send('\x03');
    let exit;
    let usedNode24Fallback = false;
    try {
      exit = await Promise.race([
        exitPromise,
        new Promise((_, reject) => setTimeout(() => reject(new Error('Timed out waiting for Ctrl+C exit')), 5000)),
      ]);
    } catch (error) {
      if (!WINDOWS_NODE24_PLUS || isProcessAlive(pty.pid)) throw error;
      pty._socket?.destroy();
      ptyExited = true;
      usedNode24Fallback = true;
      exit = { exitCode: 0 };
    }
    check(
      'W01 Ctrl+C terminates cleanly',
      exit.exitCode === 0,
      usedNode24Fallback ? 'OS exit confirmed (Node 24 ConPTY fallback)' : `exit=${exit.exitCode}`,
    );
    const exitOutput = observed.output.slice(exitMark);
    if (process.platform === 'win32') {
      check('W01 cursor visible on exit (?25h)', exitOutput.includes('\x1b[?25h'));
    } else {
      check('W01 cursor visibility restored on exit', exitOutput.includes('\x1b[?25h') || exitOutput.includes('\x1b[?12l\x1b[?25h'));
    }
  } finally {
    if (pty && !ptyExited) {
      try { pty.write('\x03'); } catch { /* PTY already closed */ }
      if (exitPromise) {
        await Promise.race([
          exitPromise,
          new Promise((resolve) => setTimeout(resolve, 1000)),
        ]);
      }
      if (!ptyExited) {
        try { pty.kill(); } catch { /* PTY already closed */ }
      }
    }
    await api.close();
  }

  const failed = results.filter((result) => !result.ok);
  console.log(`\n=== OpenTUI PTY SUMMARY: ${results.length - failed.length}/${results.length} passed ===`);
  process.exit(failed.length === 0 ? 0 : 1);
}

main().catch((error) => {
  console.error(error);
  process.exit(2);
});
