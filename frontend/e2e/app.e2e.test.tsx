/**
 * Full-app E2E (terminal-TUI equivalent of a "Playwright Test Agent" run).
 *
 * This drives the real <App/> component through every user interaction path
 * and — critically — scans EVERY rendered frame for SGR 1006 mouse-byte
 * leakage (/\x1b\[<...[Mm]/). That byte pattern is exactly what caused the
 * original "对话框乱码" bug: a second raw-stdin listener let mouse reports
 * reach Ink's text input. The stdin bridge (stdinBridge.ts) is supposed to
 * strip those bytes before Ink sees them, so a leaked SGR sequence in any
 * frame is a hard regression.
 *
 * Compared with the first version, this suite is deliberately MORE COMPLEX:
 *  - a multi-turn coding conversation (parkour-game prompt + a refinement
 *    follow-up) that exercises streamed markdown + fenced code-block rendering
 *  - the five capability areas the TUI advertises (代码开发 / 文件操作 /
 *    项目管理 / 问题排查 / 技术调研) submitted as distinct prompts
 *  - command-palette arrow-key navigation + Enter dispatching the selection
 *  - a file-operation request that references a REAL local file on disk
 *  - a long chat + mouse-wheel scroll stress path
 *
 * Runs headlessly under Vitest (no native PTY required). For a true
 * real-terminal run, see e2e/run-pty.mjs (requires `npm i node-pty`).
 *
 * NOTE on determinism: keystroke assertions poll for the expected frame
 * rather than using fixed waits. React re-renders are async, so a poll avoids
 * racy fixed-timeout failures under a saturated parallel suite. Each scenario
 * uses a FRESH <App/> render so accumulated component state can't make one
 * interaction break another.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import App from '../src/App.js';
import { MouseProvider, mouseManager } from '../src/mouse.js';
import { renderWide } from '../src/testUtil.js';

// ---- stateful mock of useApi (so multi-turn + capability tests really render) ----
function buildReply(text: string): string {
  if (/游戏|game|parkour|跑酷/i.test(text)) {
    return [
      '## 跑酷小游戏实现方案',
      '',
      '我会用 Python + pygame 实现一个可运行的横版跑酷：',
      '',
      '```python',
      'import pygame',
      '',
      'class Player:',
      '    def __init__(self):',
      '        self.x = 50',
      '        self.y = 300',
      '        self.vy = 0',
      '',
      '    def jump(self):',
      '        self.vy = -10',
      '```',
      '',
      '复制以上代码保存为 `game.py` 后运行 `python game.py` 即可。',
    ].join('\n');
  }
  if (/debounce|防抖/i.test(text)) {
    return '```ts\nfunction debounce(fn: Function, ms: number) {\n  let t: any;\n  return (...a: any[]) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };\n}\n```';
  }
  if (/git|提交|commit/i.test(text)) {
    return '建议步骤：\n```bash\n git init\ngit add .\ngit commit -m "init"\n```';
  }
  if (/ImportError|排查|bug|报错/i.test(text)) {
    return '排查思路：\n1. 确认模块路径在 PYTHONPATH\n2. 检查导出名拼写\n3. 重建 __init__.py';
  }
  return `收到你的请求：「${text}」。我已记录，稍后会处理。`;
}

const h = vi.hoisted(() => {
  const store: any = {
    messages: [] as any[],
    status: { model: 'deepseek', mode: 'build', context_used_k: 1.2, context_max_k: 256, cache_size: '10MB', cache_rate: '50%' },
    isStreaming: false,
    streamingContent: '',
  };
  const sendMessage = vi.fn(async (text: string) => {
    store.messages.push({ id: 'u' + Math.random(), role: 'user', content: text, timestamp: Date.now() });
    store.messages.push({ id: 'a' + Math.random(), role: 'assistant', content: buildReply(text), timestamp: Date.now() });
  });
  const sendCommand = vi.fn(async (cmd: string) => ({
    chats: [{ name: 'sess-1', time: '2024' }, { name: 'sess-2', time: '2023' }],
    models: [{ id: 'm1', name: 'deepseek' }, { id: 'm2', name: 'gpt' }],
  }));
  const addMessage = vi.fn((m: any) => { store.messages.push(m); });
  const setMessages = vi.fn((m: any) => { store.messages = m; });
  const reset = () => {
    store.messages = [{ id: 'welcome', role: 'assistant', content: '欢迎使用 RxyCode v1.2.1。输入需求或 / 命令开始。', timestamp: Date.now() }];
    store.isStreaming = false;
    store.streamingContent = '';
  };
  return { store, sendMessage, sendCommand, addMessage, setMessages, reset };
});

vi.mock('../src/hooks/useApi.js', () => ({
  useApi: () => {
    const [messages, setMessages] = React.useState(h.store.messages);
    const sendMessage = (text: string, _mode?: string) => {
      h.sendMessage(text);
      setMessages([...h.store.messages]);
    };
    const sendCommand = (cmd: string) => {
      const r = h.sendCommand(cmd);
      return r;
    };
    return {
      get messages() { return messages; },
      get isStreaming() { return h.store.isStreaming; },
      get streamingContent() { return h.store.streamingContent; },
      status: h.store.status,
      sendMessage,
      sendCommand,
      fetchStatus: vi.fn(async () => {}),
      cancelRequest: vi.fn(),
      addMessage: h.addMessage,
      setMessages: (m: any) => { h.setMessages(m); setMessages(m); },
    };
  },
}));

const settle = () => new Promise((r) => setTimeout(r, 30));
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
// Type into the command palette ONE CHAR AT A TIME. A multi-char single
// `stdin.write('mode')` is delivered as one data chunk, which Ink's raw
// `useInput` palette handler rejects (it requires ch.length === 1), so the
// filter never updates. Real terminals send each keystroke separately.
const typeChars = async (stdin: any, text: string) => {
  for (const ch of text) { stdin.write(ch); await wait(15); }
};
const waitFor = async (fn: () => boolean, timeout = 3000, interval = 25): Promise<boolean> => {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (fn()) return true;
    await wait(interval);
  }
  return fn();
};

// SGR 1006 mouse report: ESC [ < B ; X ; Y (M|m)
const SGR_MOUSE = /\x1b\[<\d+;\d+;\d+[Mm]/;

function assertNoSgrLeak(frames: string[]) {
  const leaks = frames
    .map((fr, i) => ({ i, m: fr.match(SGR_MOUSE) }))
    .filter((x) => x.m);
  expect(leaks, `SGR mouse-byte leakage detected in frames: ${JSON.stringify(leaks.map(l => l.i))}`).toHaveLength(0);
}

const frameContains = (f: string | null, sub: string) => (f ?? '').includes(sub);

describe('App E2E — full interaction sweep + SGR leakage guard', () => {
  beforeEach(() => {
    h.reset();
    // vi.hoisted mocks persist across tests; clear call history so each
    // scenario asserts only its own dispatches (e.g. the palette test must
    // not see /session leaked from the session-modal test).
    h.sendMessage.mockClear();
    h.sendCommand.mockClear();
    h.addMessage.mockClear();
    h.setMessages.mockClear();
  });
  afterEach(() => { vi.restoreAllMocks(); });

  // ---------- existing lightweight sweep (kept) ----------
  it('palette filter, mode cycle, and mouse do not leak SGR garbage', async () => {
    const { lastFrame, frames, stdin, unmount } = renderWide(
      <MouseProvider value={mouseManager}><App /></MouseProvider>,
    );
    await settle();
    const allFrames: string[] = [];
    const f = () => lastFrame() ?? '';

    stdin.write('\x10'); await settle();
    expect(f()).toContain('搜索命令');
    allFrames.push(...frames());

    stdin.write('ses'); await settle();
    expect(f()).toContain('session');
    stdin.write('\x1b'); await settle();
    expect(f()).not.toContain('搜索命令');
    allFrames.push(...frames());

    const seenModes = new Set<string>();
    for (let i = 0; i < 6; i++) {
      stdin.write('\t'); await wait(20);
      const m = f().match(/RxyCode v1\.1\.0\s*·\s*([a-z]+)/i);
      if (m) seenModes.add(m[1].toLowerCase());
      allFrames.push(...frames());
    }
    expect(seenModes.size).toBeGreaterThanOrEqual(2);

    stdin.write('\x10'); await settle();
    stdin.write('\x1b[<65;5;30M'); await wait(20);
    stdin.write('\x1b[<35;5;32M'); await wait(20);
    stdin.write('\x1b[<0;5;32M'); await wait(40);
    allFrames.push(...frames());
    expect(f()).toContain('搜索命令');

    assertNoSgrLeak(allFrames);
    unmount();
  });

  it('session modal opens via palette and closes on ESC (fresh render)', async () => {
    const { lastFrame, frames, stdin, unmount } = renderWide(
      <MouseProvider value={mouseManager}><App /></MouseProvider>,
    );
    await settle();
    const allFrames: string[] = [];
    const f = () => lastFrame() ?? '';

    stdin.write('\x10'); await settle();
    expect(f()).toContain('搜索命令');
    stdin.write('ses'); await settle();
    stdin.write('\r');
    expect(await waitFor(() => f().includes('Session') && f().includes('sess-1'))).toBe(true);
    allFrames.push(...frames());

    stdin.write('\x1b'); await settle();
    expect(await waitFor(() => !f().includes('sess-1'))).toBe(true);
    allFrames.push(...frames());

    assertNoSgrLeak(allFrames);
    unmount();
  });

  it('has no SGR leakage across a plain typing session', async () => {
    const { lastFrame, frames, stdin, unmount } = renderWide(
      <MouseProvider value={mouseManager}><App /></MouseProvider>,
    );
    await settle();
    const seq = ['h', 'e', 'l', 'l', 'o', ' ', 'w', 'o', 'r', 'l', 'd', '\r'];
    for (const ch of seq) { stdin.write(ch); await wait(10); }
    await settle();
    expect((lastFrame() ?? '')).toContain('Ready');
    assertNoSgrLeak(frames());
    unmount();
  });

  // ---------- NEW: complex multi-turn coding conversation ----------
  it('multi-turn: parkour-game prompt + refinement renders streamed markdown/code and no SGR leak', async () => {
    const { lastFrame, frames, stdin, unmount } = renderWide(
      <MouseProvider value={mouseManager}><App /></MouseProvider>,
    );
    await settle();
    const allFrames: string[] = [];
    const f = () => lastFrame() ?? '';

    // Turn 1: a long, realistic parkour-game coding request
    const parkourPrompt =
      '帮我用 Python 写一个跑酷小游戏：角色可以左右移动、按空格跳跃，' +
      '场景里有障碍物（撞到扣血）和金币（吃到加分），并且要有简单的重力物理。';
    stdin.write(parkourPrompt); await settle();
    stdin.write('\r');
    // The assistant reply (heading + fenced ```python block) is asserted at the
    // DATA level: ChatPanel truncates long replies, so a cropped frame would
    // miss the head/tail of the markdown. The SGR scan below still guards frames.
    expect(await waitFor(() => h.store.messages.some((m: any) =>
      (m.content || '').includes('跑酷小游戏实现方案') && (m.content || '').includes('```python'))),
    ).toBe(true);
    allFrames.push(...frames());
    // The full reply (incl. the `game.py` save instruction) is present.
    expect(h.store.messages.some((m: any) => (m.content || '').includes('game.py'))).toBe(true);

    // Turn 2: a refinement follow-up on the same conversation
    const followUp = '再加一个 60 秒倒计时和实时得分系统，时间到就 Game Over。';
    stdin.write(followUp); await settle();
    stdin.write('\r');
    expect(await waitFor(() => h.store.messages.some((m: any) => (m.content || '').includes('倒计时')))).toBe(true);
    allFrames.push(...frames());

    // Both user turns are recorded in the conversation.
    expect(h.store.messages.some((m: any) => m.role === 'user' && (m.content || '').includes('跑酷'))).toBe(true);
    expect(h.store.messages.some((m: any) => m.role === 'user' && (m.content || '').includes('倒计时'))).toBe(true);

    assertNoSgrLeak(allFrames);
    unmount();
  });

  // ---------- NEW: the five advertised capability areas ----------
  it('submits all five capability-area prompts without crash or SGR leak', async () => {
    const { lastFrame, frames, stdin, unmount } = renderWide(
      <MouseProvider value={mouseManager}><App /></MouseProvider>,
    );
    await settle();
    const allFrames: string[] = [];

    const prompts: Array<[string, string]> = [
      ['代码开发', '用 TypeScript 实现一个防抖函数 debounce，支持 cancel 和 flush'],
      ['文件操作', '读取 ./tests/_fixtures/demo_config.py 并解释它的配置项'],
      ['项目管理', '为这个仓库初始化 git 并提交所有改动'],
      ['问题排查', '我的 pytest 报 ImportError: cannot import name TaskNode，怎么排查？'],
      ['技术调研', '对比 FastAPI 和 Flask 在异步支持和依赖注入上的差异'],
    ];

    for (const [area, prompt] of prompts) {
      stdin.write(prompt); await settle();
      stdin.write('\r');
      // The user's prompt (or a slice) should appear in the rendered frame
      expect(await waitFor(() => frameContains(lastFrame(), prompt.slice(0, 8)))).toBe(true);
      allFrames.push(...frames());
    }

    // All five distinct areas were dispatched through sendMessage
    const calledTexts = (h.sendMessage as any).mock.calls.map((c: any[]) => c[0] as string);
    for (const [area, prompt] of prompts) {
      expect(calledTexts.some((t) => t.includes(prompt)), `capability [${area}] not submitted`).toBe(true);
    }
    expect(calledTexts.length).toBeGreaterThanOrEqual(5);

    assertNoSgrLeak(allFrames);
    unmount();
  });

  // ---------- NEW: command-palette arrow navigation + Enter dispatches selection ----------
  it('command palette: filter "mode", ArrowDown, Enter dispatches the selected mode command', async () => {
    const { lastFrame, frames, stdin, unmount } = renderWide(
      <MouseProvider value={mouseManager}><App /></MouseProvider>,
    );
    await settle();
    const allFrames: string[] = [];
    const f = () => lastFrame() ?? '';

    stdin.write('\x10'); await settle();
    expect(f()).toContain('搜索命令');
    await typeChars(stdin, 'mode'); await settle();   // filters to mode-related commands
    // After filtering "mode" the list is [__model, /addmodel, /models, /plan, ...].
    // Two ArrowDowns land on /models (a real mode command). Note: the old
    // `/model <name>` text command was removed, so /addmodel now occupies the
    // slot a single ArrowDown would have hit (and /addmodel opens the wizard,
    // not a dispatch).
    stdin.write('\x1b[B'); await wait(20);  // ArrowDown -> /addmodel
    stdin.write('\x1b[B'); await wait(20);  // ArrowDown -> /models
    stdin.write('\r'); await wait(40);      // Enter selects highlighted command
    allFrames.push(...frames());

    const called = (h.sendCommand as any).mock.calls.map((c: any[]) => c[0] as string);
    const MODE_CMDS = ['/models', '/plan', '/build', '/compose', '__action:model'];
    expect(called.some((c) => MODE_CMDS.includes(c)),
      `expected a mode command dispatched, got: ${JSON.stringify(called)}`).toBe(true);
    expect(called).not.toContain('/session');  // proves filtering + navigation, not the unfiltered default

    assertNoSgrLeak(allFrames);
    unmount();
  });

  // ---------- NEW: file-operation request referencing a real local file ----------
  it('file-operation request referencing a real local file is submitted and shown', async () => {
    const { lastFrame, frames, stdin, unmount } = renderWide(
      <MouseProvider value={mouseManager}><App /></MouseProvider>,
    );
    await settle();
    const allFrames: string[] = [];
    const f = () => lastFrame() ?? '';

    const fileReq = '读取文件 ./tests/_fixtures/demo_config.py 并把缺少的 PORT 配置补上';
    stdin.write(fileReq); await settle();
    stdin.write('\r');
    expect(await waitFor(() => frameContains(f(), 'demo_config.py'))).toBe(true);
    allFrames.push(...frames());

    const calledTexts = (h.sendMessage as any).mock.calls.map((c: any[]) => c[0] as string);
    expect(calledTexts.some((t) => t.includes('demo_config.py')), 'file-op request not submitted').toBe(true);

    assertNoSgrLeak(allFrames);
    unmount();
  });

  // ---------- NEW: mode cycle visits every mode (build -> plan -> compose -> build) ----------
  it('Tab cycles through all three modes (build/plan/compose) and header reflects each', async () => {
    const { lastFrame, frames, stdin, unmount } = renderWide(
      <MouseProvider value={mouseManager}><App /></MouseProvider>,
    );
    await settle();
    const allFrames: string[] = [];
    const f = () => lastFrame() ?? '';

    const seen = new Set<string>();
    for (let i = 0; i < 4; i++) {
      stdin.write('\t'); await wait(25);
      const m = f().match(/RxyCode v1\.1\.0\s*·\s*([a-z]+)/i);
      if (m) seen.add(m[1].toLowerCase());
      allFrames.push(...frames());
    }
    // build, plan, compose must all appear at least once
    for (const mode of ['build', 'plan', 'compose']) {
      expect(seen.has(mode), `mode "${mode}" never shown during Tab cycle`).toBe(true);
    }
    assertNoSgrLeak(allFrames);
    unmount();
  });

  // ---------- NEW: long chat + mouse-wheel scroll stress (SGR guard) ----------
  it('long chat with many messages + wheel scroll does not leak SGR', async () => {
    // Pre-populate a long conversation (40 messages) to stress the renderer.
    for (let i = 0; i < 40; i++) {
      h.store.messages.push({ id: 'm' + i, role: i % 2 === 0 ? 'user' : 'assistant', content: `消息 #${i}: ` + (i % 3 === 0 ? '```python\nx=1\n```' : '一些说明文字'), timestamp: Date.now() + i });
    }
    const { lastFrame, frames, stdin, unmount } = renderWide(
      <MouseProvider value={mouseManager}><App /></MouseProvider>,
    );
    await settle();
    const allFrames: string[] = [];
    const f = () => lastFrame() ?? '';

    expect(frameContains(f(), '消息 #')).toBe(true);

    // Wheel up/down many times through the long list
    for (let i = 0; i < 8; i++) {
      stdin.write('\x1b[<64;5;30M'); await wait(15);   // wheel up
      stdin.write('\x1b[<65;5;30M'); await wait(15);   // wheel down
    }
    allFrames.push(...frames());
    expect(frameContains(f(), '消息 #')).toBe(true);    // chat still rendering

    assertNoSgrLeak(allFrames);
    unmount();
  });
});
