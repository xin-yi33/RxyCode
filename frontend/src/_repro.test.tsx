import { describe, it, vi, afterEach } from 'vitest';
import React from 'react';
import { render as inkRender } from 'ink';
import { EventEmitter } from 'node:events';
import App from './App.js';
import { MouseProvider, mouseManager } from './mouse.js';

vi.mock('./hooks/useApi.js', () => ({
  useApi: () => ({
    messages: [], streamingContent: '', isStreaming: false,
    status: { model: 'deepseek', mode: 'build', context_used_k: 1.2, context_max_k: 256, cache_size: '10MB', cache_rate: '50%' },
    sendMessage: async () => {},
    sendCommand: async () => ({ chats: [{ name: 'sess-1', time: '2024' }], models: [{ id: 'm1', name: 'deepseek' }] }),
    fetchStatus: async () => {}, cancelRequest: () => {}, addMessage: () => {}, setMessages: () => {},
  }),
}));

function renderN(tree: React.ReactElement, cols: number, rows: number) {
  class Stdout extends EventEmitter {
    columns = cols; rows = rows; frames: string[] = []; private _last?: string;
    write = (f: string) => { this.frames.push(f); this._last = f; }; lastFrame = () => this._last;
  }
  class Stdin extends EventEmitter {
    isTTY = true; data: string | null = null; setRawMode = () => {}; setEncoding = () => {};
    resume = () => {}; pause = () => {}; ref = () => {}; unref = () => {};
    write = (d: string) => { this.data = d; this.emit('readable'); this.emit('data', d); };
    read = () => { const { data } = this; this.data = null; return data; };
  }
  const stdout = new Stdout(); const stdin = new Stdin();
  const app = inkRender(tree, { stdout: stdout as any, stdin: stdin as any, exitOnCtrlC: false, patchConsole: false, debug: true });
  return { lastFrame: () => stdout.lastFrame(), stdin, unmount: () => app.unmount() };
}
const settle = (ms = 40) => new Promise((r) => setTimeout(r, ms));
const type = (s: any, t: string) => s.write(t);
const cnt = (f: string, n: string) => f.split(n).length - 1;

describe('repro 80x24', () => {
  afterEach(() => vi.restoreAllMocks());
  it('idle 80x24', async () => {
    const { lastFrame, unmount } = renderN(<MouseProvider value={mouseManager}><App /></MouseProvider>, 80, 24);
    await settle(80);
    const f = lastFrame() ?? '';
    console.log('\n===== IDLE 80x24 =====\n' + f + '\n===== END =====');
    console.log('build·Ready=', cnt(f, 'build · Ready'), ' 输入指令=', cnt(f, '输入指令或需求'), ' ╭=', cnt(f, '╭'));
    unmount();
  });
  it('addmodel 80x24', async () => {
    const { lastFrame, stdin, unmount } = renderN(<MouseProvider value={mouseManager}><App /></MouseProvider>, 80, 24);
    await settle(80);
    type(stdin, '/addmodel'); await settle(); stdin.write('\r'); await settle(150);
    const f = lastFrame() ?? '';
    console.log('\n===== ADDMODEL 80x24 =====\n' + f + '\n===== END =====');
    console.log('build·Ready=', cnt(f, 'build · Ready'), ' 输入指令=', cnt(f, '输入指令或需求'), ' ╭=', cnt(f, '╭'), ' Session=', cnt(f, 'Session'), ' 请输入模型=', cnt(f, '请输入模型'));
    unmount();
  });
});
