/**
 * Real PTY/ConPTY smoke test for the built RxyCode TUI.
 *
 * The harness owns a deterministic local API server, starts dist/index.js in a
 * real pseudo-terminal, drives resize/keyboard/paste/mouse input, and verifies
 * terminal modes are restored on normal and uncaught-error exits.
 * Run `npm run build && npm run e2e`.
 */
import { createServer } from 'node:http';
import { spawnSync } from 'node:child_process';
import { createConnection } from 'node:net';
import { spawn } from 'node-pty';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const APP_BIN = process.env.RXYCODE_E2E_APP_BIN || join(ROOT, 'dist', 'index.js');
const CRASH_PRELOAD = join(ROOT, 'e2e', 'fixtures', 'crash-trigger.cjs');
const COLS = 80;
const ROWS = 24;
const NARROW_COLS = 52;
const NARROW_ROWS = 18;
const TIMEOUT_MS = 8000;
const SGR_MOUSE = /\x1b\[<\d+;\d+;\d+[Mm]/;
const ANSI_CONTROL = /\x1b\[[0-?]*[ -/]*[@-~]/g;
const plain = (value) => value.replace(ANSI_CONTROL, '');
const WINDOWS_NODE24_PLUS = process.platform === 'win32'
  && Number.parseInt(process.versions.node.split('.')[0], 10) >= 24;

const isProcessAlive = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code !== 'ESRCH';
  }
};

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  - ${detail}` : ''}`);
}

function startMockApi() {
  const chatRequests = [];
  const chatRequestListeners = new Set();
  const cancelledChatRequests = [];
  const cancellationListeners = new Set();
  const logEntries = [];
  const logListeners = new Set();
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

      if (request.method === 'POST' && request.url === '/log') {
        let entry = {};
        try { entry = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { /* invalid body */ }
        logEntries.push(entry);
        for (const listener of logListeners) listener(entry);
        response.writeHead(204);
        response.end();
        return;
      }

      if (request.method === 'POST' && request.url === '/command') {
        let command = '';
        try { command = JSON.parse(Buffer.concat(chunks).toString('utf8')).command ?? ''; } catch { /* invalid body */ }
        response.writeHead(200, { 'content-type': 'application/json' });
        if (command === '/session' || command === '/list-chats') {
          response.end(JSON.stringify({ chats: [{ name: 'pty-session', time: '2026-01-01' }] }));
        } else {
          response.end(JSON.stringify({ message: `ok: ${command}` }));
        }
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
          response.once('close', () => {
            cancelledChatRequests.push(body);
            for (const listener of cancellationListeners) listener(body);
          });
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
        cancelledChatRequests,
        logEntries,
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
        waitForCancellation: (predicate = () => true, timeoutMs = TIMEOUT_MS) => {
          const existing = cancelledChatRequests.find(predicate);
          if (existing) return Promise.resolve(existing);
          return new Promise((done, fail) => {
            const timer = setTimeout(() => {
              cancellationListeners.delete(onCancellation);
              fail(new Error('Timed out waiting for mock chat cancellation'));
            }, timeoutMs);
            const onCancellation = (body) => {
              if (!predicate(body)) return;
              clearTimeout(timer);
              cancellationListeners.delete(onCancellation);
              done(body);
            };
            cancellationListeners.add(onCancellation);
          });
        },
        waitForLog: (predicate, timeoutMs = TIMEOUT_MS) => {
          const existing = logEntries.find(predicate);
          if (existing) return Promise.resolve(existing);
          return new Promise((done, fail) => {
            const timer = setTimeout(() => {
              logListeners.delete(onLog);
              fail(new Error('Timed out waiting for mock log entry'));
            }, timeoutMs);
            const onLog = (entry) => {
              if (!predicate(entry)) return;
              clearTimeout(timer);
              logListeners.delete(onLog);
              done(entry);
            };
            logListeners.add(onLog);
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
  const chunks = [];
  const listeners = new Set();
  pty.onData((chunk) => {
    output += chunk;
    chunks.push(chunk);
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
      const tail = plain(output.slice(-500)).replace(/\s+/g, ' ').trim();
      const rawTail = JSON.stringify(output.slice(-240));
      finish(new Error(`Timed out waiting for ${label}; output tail: ${tail}; raw tail: ${rawTail}`));
    }, timeoutMs);
    listeners.add(test);
    test();
  });

  const waitForIdle = (label, quietMs = 50, timeoutMs = TIMEOUT_MS) => new Promise((resolve, reject) => {
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
    get chunks() { return chunks; },
    mark: () => output.length,
    waitFor,
    waitForIdle,
  };
}

async function verifyCrashRestoration(apiUrl) {
  const crashEnv = {
    ...process.env,
    TERM: 'xterm-256color',
    FORCE_COLOR: '1',
    RXYCODE_API_URL: apiUrl,
    RXYCODE_E2E_BYPASS_TTY: '1',
    CI: 'false',
  };
  delete crashEnv.RXYCODE_MOUSE;

  const crashPty = spawn(process.execPath, ['--require', CRASH_PRELOAD, APP_BIN], {
    name: 'xterm-256color',
    cwd: ROOT,
    cols: COLS,
    rows: ROWS,
    env: crashEnv,
    ...(process.platform === 'win32' ? { useConpty: true } : {}),
  });
  const observed = observePty(crashPty);
  let exited = false;
  const exitPromise = new Promise((resolve) => crashPty.onExit((event) => {
    exited = true;
    resolve(event);
  }));

  try {
    await observed.waitFor(
      (output) => /RXYCODE_CRASH_PORT=\d+/.test(plain(output)) && /Ready/.test(plain(output)),
      'crash-path TUI boot',
    );
    const portMatch = plain(observed.output).match(/RXYCODE_CRASH_PORT=(\d+)/);
    if (!portMatch) throw new Error('Crash fixture did not publish its control port');
    const crashMark = observed.mark();
    await new Promise((resolve, reject) => {
      const socket = createConnection({ host: '127.0.0.1', port: Number(portMatch[1]) });
      socket.once('error', reject);
      socket.once('connect', () => {
        socket.end('crash');
        resolve();
      });
    });
    let exit;
    let usedNode24Fallback = false;
    try {
      exit = await Promise.race([
        exitPromise,
        new Promise((_, reject) => setTimeout(() => reject(new Error('Timed out waiting for injected crash')), 3000)),
      ]);
    } catch (error) {
      if (!WINDOWS_NODE24_PLUS || isProcessAlive(crashPty.pid)) throw error;
      crashPty._socket?.destroy();
      exited = true;
      usedNode24Fallback = true;
      exit = { exitCode: 1 };
    }

    const crashOutput = observed.output.slice(crashMark);
    check(
      'Injected uncaught error exits non-zero',
      exit.exitCode !== 0,
      usedNode24Fallback ? 'OS exit confirmed (Node 24 ConPTY fallback)' : `exit=${exit.exitCode}`,
    );
    check(
      'Terminal restored after uncaught error',
      crashOutput.includes('\x1b[?25h') && crashOutput.includes('\x1b[?2004l'),
    );
  } finally {
    if (!exited) {
      try { crashPty.kill(); } catch { /* PTY already closed */ }
    }
  }
}

async function main() {
  if (process.env.RXYCODE_E2E_SCENARIO === 'crash-restoration') {
    const crashApi = await startMockApi();
    try {
      await verifyCrashRestoration(crashApi.url);
    } finally {
      await crashApi.close();
    }
    const failed = results.filter((result) => !result.ok);
    console.log(`\n=== PTY CRASH SUMMARY: ${results.length - failed.length}/${results.length} passed ===`);
    process.exit(failed.length === 0 ? 0 : 1);
    return;
  }

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
      RXYCODE_E2E_BYPASS_TTY: '1',
      // Ink's is-in-ci check skips live frame rendering when CI=true (GitHub
      // Actions sets this).  Force-disable so the TUI renders normally in the
      // ConPTY under e2e.
      CI: 'false',
    };
    delete childEnv.RXYCODE_MOUSE;
    pty = spawn(process.execPath, [APP_BIN], {
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
    const waitSince = (start, pattern, label) => observed.waitFor(
      (output) => pattern.test(plain(output.slice(start))),
      label,
    );

    await observed.waitFor((output) => /输入指令或需求|Ready/.test(plain(output)), 'TUI boot', 15000);
    check(process.platform === 'win32' ? 'Windows ConPTY boot' : 'PTY boot', true, `${COLS}x${ROWS}`);
    check('Mouse tracking disabled by default', !observed.output.includes('\x1b[?1002h'));

    let mark = observed.mark();
    pty.resize(NARROW_COLS, NARROW_ROWS);
    await waitSince(mark, /Ready/, 'narrow resize rerender');
    mark = observed.mark();
    pty.resize(COLS, ROWS);
    await waitSince(mark, /Ready/, 'restored resize rerender');
    check(
      process.platform === 'win32' ? 'ConPTY resize rerenders live layout' : 'PTY resize rerenders live layout',
      true,
      `${COLS}x${ROWS} -> ${NARROW_COLS}x${NARROW_ROWS} -> ${COLS}x${ROWS}`,
    );

    mark = observed.mark();
    send('PTY_CANCEL_ME');
    await waitSince(mark, /PTY_CANCEL_ME/, 'cancellation prompt input');
    send('\r');
    await api.waitForChatRequest((body) => body.message === 'PTY_CANCEL_ME');
    await waitSince(mark, /PTYWAITING|Processing/, 'cancellable stream');
    const cancelMark = observed.mark();
    send('\x03');
    await Promise.all([
      api.waitForCancellation((body) => body.message === 'PTY_CANCEL_ME'),
      waitSince(cancelMark, /Cancelled/, 'Ctrl+C cancellation result'),
    ]);
    check('Ctrl+C cancels the active stream without exiting', !ptyExited && api.cancelledChatRequests.length === 1);

    mark = observed.mark();
    send('\x10');
    await waitSince(mark, /搜索命令|命令面板/, 'command palette open');
    await observed.waitForIdle('command palette to settle');
    check('Ctrl+P opens command palette', true);

    mark = observed.mark();
    send('\x1b');
    await observed.waitForIdle('input to regain focus');
    mark = observed.mark();
    send('Z');
    await waitSince(mark, /Z/, 'input focus probe');
    mark = observed.mark();
    send('\x7f');
    await waitSince(mark, /输入指令或需求/, 'input focus probe cleanup');
    check('ESC closes command palette', true);

    mark = observed.mark();
    send('\t');
    await waitSince(mark, /plan/i, 'mode change');
    check('Tab cycles mode', true);

    mark = observed.mark();
    send('/session');
    await waitSince(mark, /\/session/, 'session command input');
    mark = observed.mark();
    send('\r');
    await waitSince(mark, /pty-session/, 'session modal');
    check('/session opens deterministic modal', true);
    send('\x1b');
    await observed.waitForIdle('modal close to settle');

    mark = observed.mark();
    send('\x10');
    await waitSince(mark, /搜索命令|命令面板/, 'palette reopen');
    await observed.waitForIdle('reopened palette to settle');
    send('\x1b[<65;5;18M');
    send('\x1b[<35;5;18M');
    send('\x1b[<0;5;18M');
    check('Injected mouse reports do not leak', !SGR_MOUSE.test(observed.output));
    send('\x1b');
    await observed.waitForIdle('paste target to settle');

    mark = observed.mark();
    send('\x1b[200~PASTE_FIRST\r\nPASTE_SECOND\x1b[201~');
    await waitSince(mark, /PASTE_FIRST[\s\S]*PASTE_SECOND/, 'multi-line paste render');
    await observed.waitForIdle('multi-line paste to settle');
    send('\r');
    const chatRequest = await api.waitForChatRequest((body) => body.message === 'PASTE_FIRST\nPASTE_SECOND');
    check(
      'Mock API receives one multi-line prompt',
      api.chatRequests.filter((body) => body.message === 'PASTE_FIRST\nPASTE_SECOND').length === 1
        && chatRequest.message === 'PASTE_FIRST\nPASTE_SECOND',
      JSON.stringify(chatRequest.message),
    );
    await api.waitForLog((entry) => entry.message === 'Stream event' && entry.context?.type === 'final');
    check(
      'SSE final event parsed',
      api.logEntries.some((entry) => entry.message === 'Stream event' && entry.context?.type === 'final'),
    );
    await waitSince(mark, /PTYREPLYOK/, 'pasted prompt response');
    check('Bracketed multi-line paste reaches one request', true);

    mark = observed.mark();
    send('PTY_LONG_STREAM');
    await waitSince(mark, /PTY_LONG_STREAM/, 'long stream prompt input');
    send('\r');
    await api.waitForChatRequest((body) => body.message === 'PTY_LONG_STREAM');
    await waitSince(mark, /LONGASSISTANT079/, 'long stream final response');
    await observed.waitForIdle('long stream to settle', 120);
    const longOutput = plain(observed.output.slice(mark));
    const count = (needle) => longOutput.split(needle).length - 1;
    check('Long assistant head is not redrawn into scrollback', count('LONGASSISTANT000') === 1, `count=${count('LONGASSISTANT000')}`);
    check('Long assistant tail is visible after final', count('LONGASSISTANT079') >= 1, `count=${count('LONGASSISTANT079')}`);
    check('Completed long tool body remains folded', !longOutput.includes('LONGTOOL000') && !longOutput.includes('LONGTOOL079'));
    check('Header does not form an adjacent duplicate block', !/RxyCode v1\.1\.0[^\r\n]*[\r\n\s]+RxyCode v1\.1\.0/.test(longOutput));

    mark = observed.mark();
    send('/exit');
    await waitSince(mark, /\/exit/, 'exit command input');
    await observed.waitForIdle('exit command to settle');
    const exitMark = observed.mark();
    send('\r');
    let exit;
    let usedNode24Fallback = false;
    try {
      exit = await Promise.race([
        exitPromise,
        new Promise((_, reject) => setTimeout(() => reject(new Error('Timed out waiting for /exit')), 3000)),
      ]);
    } catch (error) {
      if (!WINDOWS_NODE24_PLUS || isProcessAlive(pty.pid)) throw error;
      // node-pty 1.1.0 can miss the ConPTY close callback on Node 24 even
      // though the child is gone. Close only the stale output handle; Node 22
      // CI still requires the native onExit path above.
      pty._socket?.destroy();
      ptyExited = true;
      usedNode24Fallback = true;
      exit = { exitCode: 0 };
    }
    check(
      '/exit terminates cleanly',
      exit.exitCode === 0,
      usedNode24Fallback ? 'OS exit confirmed (Node 24 ConPTY fallback)' : `exit=${exit.exitCode}`,
    );
    const exitOutput = observed.output.slice(exitMark);
    if (process.platform === 'win32') {
      check('Cursor visible on exit', exitOutput.includes('\x1b[?25h'));
    } else {
      check('Bracketed paste mode restored', exitOutput.includes('\x1b[?2004l'));
      check('Cursor visibility and blink restored', exitOutput.includes('\x1b[?12l\x1b[?25h'));
    }
    check('No SGR mouse bytes in captured output', observed.chunks.every((chunk) => !SGR_MOUSE.test(chunk)));
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

  const crashRun = spawnSync(process.execPath, [fileURLToPath(import.meta.url)], {
    cwd: ROOT,
    env: { ...process.env, RXYCODE_E2E_SCENARIO: 'crash-restoration' },
    stdio: 'inherit',
  });
  if (crashRun.error) throw crashRun.error;
  if (crashRun.status !== 0) {
    throw new Error(`Crash-restoration PTY scenario failed with exit ${crashRun.status}`);
  }

  const failed = results.filter((result) => !result.ok);
  console.log(`\n=== PTY SUMMARY: ${results.length - failed.length}/${results.length} passed ===`);
  process.exit(failed.length === 0 ? 0 : 1);
}

main().catch((error) => {
  console.error(error);
  process.exit(2);
});
