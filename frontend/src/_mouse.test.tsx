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
  class Stdout extends EventEmitter { columns = cols; rows = rows; frames: string[] = []; private _last?: string; write = (f: string) => { this.frames.push(f); this._last = f; }; lastFrame = () => this._last; }
  class Stdin extends EventEmitter { isTTY = true; data: string | null = null; setRawMode = () => {}; setEncoding = () => {}; resume = () => {}; pause = () => {}; ref = () => {}; unref = () => {}; write = (d: string) => { this.data = d; this.emit('readable'); this.emit('data', d); }; read = () => { const { data } = this; this.data = null; return data; }; }
  const stdout = new Stdout(); const stdin = new Stdin();
  const app = inkRender(tree, { stdout: stdout as any, stdin: stdin as any, exitOnCtrlC: false, patchConsole: false, debug: true });
  return { lastFrame: () => stdout.lastFrame(), stdin, unmount: () => app.unmount() };
}
const settle = (ms = 40) => new Promise((r) => setTimeout(r, ms));
function measure(frame: string) {
  const lines = frame.split('\n');
  const topIdxs: number[] = []; const botIdxs: number[] = [];
  lines.forEach((l, i) => { if (l.includes('╭')) topIdxs.push(i); if (l.includes('╰')) botIdxs.push(i); });
  // last bordered box is the palette/modal
  const top = topIdxs[topIdxs.length - 1];
  const bot = botIdxs[botIdxs.length - 1];
  const height = bot - top + 1;
  // first item row = first line after `top` that contains '❯' (excluding search line which is the 2nd row)
  let firstItem = -1;
  for (let i = top + 1; i <= bot; i++) {
    const t = lines[i].replace(/\x1b\[[0-9;]*m/g, '');
    if (t.includes('❯') && !t.includes('搜索')) { firstItem = i; break; }
  }
  return { top, bot, height, firstItemRow: firstItem, offset: firstItem - top };
}

describe('measure', () => {
  afterEach(() => vi.restoreAllMocks());
  it('measure palette + modal', async () => {
    const { lastFrame, stdin, unmount } = renderN(<MouseProvider value={mouseManager}><App /></MouseProvider>, 80, 40);
    await settle(80);
    stdin.write('\x10'); await settle(80);
    console.log('PALETTE measure:', JSON.stringify(measure(lastFrame() ?? '')));
    // close palette
    stdin.write('\x1b'); await settle(80);
    // open model modal
    stdin.write('/models'); await settle(); stdin.write('\r'); await settle(120);
    console.log('MODAL measure:', JSON.stringify(measure(lastFrame() ?? '')));
    unmount();
  });
});
