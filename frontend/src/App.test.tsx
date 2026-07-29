import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import React from 'react';
import App from './App.js';
import { MouseProvider, mouseManager } from './mouse.js';
import { renderWide } from './testUtil.js';

const apiMocks = vi.hoisted(() => ({
  sendCommand: vi.fn(),
  addModel: vi.fn(),
  setMessages: vi.fn(),
  addMessage: vi.fn(),
}));

vi.mock('./hooks/useApi.js', () => ({
  useApi: () => ({
    messages: [],
    streamingContent: '',
    status: {
      model: 'deepseek', mode: 'build', context_used_k: 1.2, context_max_k: 256,
      cache_size: '10MB', cache_rate: '50%',
    },
    isStreaming: false,
    sendMessage: async () => {},
    sendCommand: apiMocks.sendCommand,
    addModel: apiMocks.addModel,
    fetchStatus: async () => {},
    cancelRequest: () => {},
    addMessage: apiMocks.addMessage,
    setMessages: apiMocks.setMessages,
  }),
}));

// Ink attaches its stdin `data` listener inside a useEffect. The first keystroke
// sent synchronously after render is lost, so always wait a tick before input.
const settle = () => new Promise((r) => setTimeout(r, 30));

const type = (stdin: any, text: string) => {
  // ink-text-input only registers input when the full string arrives in one
  // write; char-by-char writes are dropped by Ink's keypress buffer.
  stdin.write(text);
};

const restoredToolOutput = 'begin\n' + 'x'.repeat(1200) + '\nend';

describe('App integration', () => {
  beforeEach(() => {
    apiMocks.sendCommand.mockReset().mockImplementation(async (command: string) => {
      if (command === '/load-chat sess-1') {
        return {
          action: 'chat_loaded',
          message: 'loaded status must not be appended',
          messages: [
            { role: 'user', content: 'restored question' },
            { role: 'thinking', content: 'restored reasoning', done: true, live: false },
            { role: 'tool', content: restoredToolOutput, toolName: 'bash', toolStatus: 'success', toolStdout: restoredToolOutput },
            { role: 'assistant', content: 'restored answer' },
            { role: 'system', content: 'restored notice' },
          ],
        };
      }
      return {
        chats: [{ name: 'sess-1', time: '2024' }],
        models: [{ id: 'm1', name: 'deepseek' }],
      };
    });
    apiMocks.setMessages.mockReset();
    apiMocks.addMessage.mockReset();
    apiMocks.addModel.mockReset().mockResolvedValue({
      action: 'model_added',
      message: 'Model added',
    });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it('renders header + ready input box', async () => {
    const { lastFrame, unmount } = renderWide(<MouseProvider value={mouseManager}><App /></MouseProvider>);
    await settle();
    const f = lastFrame() ?? '';
    expect(f).toContain('RxyCode v1.2.0');
    expect(f).toContain('Ready');
    unmount();
  });

  it('Ctrl+T toggles thinking from the main input using the server state', async () => {
    apiMocks.sendCommand.mockResolvedValueOnce({ action: 'thinking_toggled', expanded: true });
    const { lastFrame, stdin, unmount } = renderWide(<MouseProvider value={mouseManager}><App /></MouseProvider>);
    await settle();
    stdin.write('\x14');
    await settle();

    expect(apiMocks.sendCommand).toHaveBeenCalledTimes(1);
    expect(apiMocks.sendCommand).toHaveBeenCalledWith('/thinking');
    expect(lastFrame()).toContain('思考:开');
    unmount();
  });

  it('Ctrl+T remains available while a modal has replaced the input box', async () => {
    const rendered = renderWide(<MouseProvider value={mouseManager}><App /></MouseProvider>);
    await settle();
    type(rendered.stdin, '/model');
    await settle();
    rendered.stdin.write('\r');
    await new Promise((r) => setTimeout(r, 80));
    expect(rendered.lastFrame()).toContain('Select Model');

    apiMocks.sendCommand.mockClear();
    apiMocks.sendCommand.mockResolvedValueOnce({ action: 'thinking_toggled', expanded: true });
    rendered.stdin.write('\x14');
    await settle();

    expect(apiMocks.sendCommand).toHaveBeenCalledTimes(1);
    expect(apiMocks.sendCommand).toHaveBeenCalledWith('/thinking');
    expect(rendered.lastFrame()).toContain('思考:开');
    rendered.unmount();
  });

  it('Ctrl+P opens the command palette, ESC closes it', async () => {
    const { lastFrame, stdin, unmount } = renderWide(<MouseProvider value={mouseManager}><App /></MouseProvider>);
    await settle();
    stdin.write('\x10'); // Ctrl+P
    await settle();
    // Palette-specific text (search placeholder) proves the palette is open.
    expect((lastFrame() ?? '')).toContain('搜索命令');
    stdin.write('\x1b'); // ESC
    await settle();
    // Palette closed -> its search box is gone. (The welcome hint "Ctrl+P 命令面板"
    // always contains "命令面板", so we must NOT assert on that string.)
    expect((lastFrame() ?? '')).not.toContain('搜索命令');
    unmount();
  });

  it('typing /session + Enter opens the Session modal', async () => {
    const { lastFrame, stdin, unmount } = renderWide(<MouseProvider value={mouseManager}><App /></MouseProvider>);
    await settle();
    type(stdin, '/session');
    await settle();
    stdin.write('\r');
    await new Promise((r) => setTimeout(r, 80));
    const f = lastFrame() ?? '';
    expect(f).toContain('Session');
    expect(f).toContain('sess-1');
    unmount();
  });

  it('selecting a session replaces the displayed history without a status message', async () => {
    const rendered = renderWide(<MouseProvider value={mouseManager}><App /></MouseProvider>);
    await settle();
    type(rendered.stdin, '/session');
    await settle();
    rendered.stdin.write('\r');
    await new Promise((r) => setTimeout(r, 80));
    rendered.stdin.write('\r');
    await new Promise((r) => setTimeout(r, 80));

    expect(apiMocks.sendCommand).toHaveBeenNthCalledWith(1, '/session');
    expect(apiMocks.sendCommand).toHaveBeenNthCalledWith(2, '/load-chat sess-1');
    expect(apiMocks.setMessages).toHaveBeenCalledTimes(1);
    expect(apiMocks.setMessages.mock.calls[0][0]).toEqual([
      expect.objectContaining({ role: 'user', content: 'restored question', id: expect.any(String), timestamp: expect.any(Number) }),
      expect.objectContaining({ role: 'thinking', content: 'restored reasoning', done: true, live: false }),
      expect.objectContaining({ role: 'tool', content: restoredToolOutput, toolName: 'bash', toolStatus: 'success', toolStdout: restoredToolOutput }),
      expect.objectContaining({ role: 'assistant', content: 'restored answer', id: expect.any(String), timestamp: expect.any(Number) }),
      expect.objectContaining({ role: 'system', content: 'restored notice' }),
    ]);
    expect(apiMocks.addMessage).not.toHaveBeenCalled();
    rendered.unmount();
  });

  it('direct /load-chat replaces the displayed history without a status message', async () => {
    const rendered = renderWide(<MouseProvider value={mouseManager}><App /></MouseProvider>);
    await settle();
    type(rendered.stdin, '/load-chat sess-1');
    await settle();
    rendered.stdin.write('\r');
    await new Promise((r) => setTimeout(r, 80));

    expect(apiMocks.sendCommand).toHaveBeenCalledWith('/load-chat sess-1');
    expect(apiMocks.setMessages).toHaveBeenCalledTimes(1);
    expect(apiMocks.setMessages.mock.calls[0][0]).toEqual([
      expect.objectContaining({ role: 'user', content: 'restored question', id: expect.any(String), timestamp: expect.any(Number) }),
      expect.objectContaining({ role: 'thinking', content: 'restored reasoning', done: true, live: false }),
      expect.objectContaining({ role: 'tool', content: restoredToolOutput, toolName: 'bash', toolStatus: 'success', toolStdout: restoredToolOutput }),
      expect.objectContaining({ role: 'assistant', content: 'restored answer', id: expect.any(String), timestamp: expect.any(Number) }),
      expect.objectContaining({ role: 'system', content: 'restored notice' }),
    ]);
    expect(apiMocks.addMessage).not.toHaveBeenCalled();
    rendered.unmount();
  });

  it('typing /exit + Enter exits the Ink application', async () => {
    const terminateProcess = vi.fn();
    const rendered = renderWide(
      <MouseProvider value={mouseManager}><App terminateProcess={terminateProcess} /></MouseProvider>,
    );
    const exited = rendered.waitUntilExit();
    await settle();
    type(rendered.stdin, '/exit');
    await settle();
    rendered.stdin.write('\r');

    await expect(Promise.race([
      exited,
      new Promise((_, reject) => setTimeout(() => reject(new Error('exit timeout')), 500)),
    ])).resolves.toBeUndefined();
    expect(terminateProcess).toHaveBeenCalledTimes(1);
  });

  it('/clear clears backend context before resetting the UI messages', async () => {
    apiMocks.sendCommand.mockResolvedValueOnce({ message: 'backend cleared' });
    const rendered = renderWide(<MouseProvider value={mouseManager}><App /></MouseProvider>);
    await settle();
    type(rendered.stdin, '/clear');
    await settle();
    rendered.stdin.write('\r');
    await settle();

    expect(apiMocks.sendCommand).toHaveBeenCalledWith('/clear');
    expect(apiMocks.setMessages).toHaveBeenCalledWith([]);
    expect(rendered.lastFrame()).toContain('Ready');
    rendered.unmount();
  });

  it('Tab cycles agent mode without crashing', async () => {
    const { lastFrame, stdin, unmount } = renderWide(<MouseProvider value={mouseManager}><App /></MouseProvider>);
    await settle();
    stdin.write('\t'); // Tab
    await new Promise((r) => setTimeout(r, 30));
    expect((lastFrame() ?? '')).toContain('Plan'); // build -> plan
    unmount();
  });

  it('typing /model + Enter opens the Model selector modal (not a text command)', async () => {
    const { lastFrame, stdin, unmount } = renderWide(<MouseProvider value={mouseManager}><App /></MouseProvider>);
    await settle();
    type(stdin, '/model');
    await settle();
    stdin.write('\r');
    await new Promise((r) => setTimeout(r, 80));
    const f = lastFrame() ?? '';
    expect(f).toContain('Select Model');
    expect(f).toContain('deepseek');
    unmount();
  });

  it('/addmodel opens the wizard popup instead of dumping steps into chat', async () => {
    const { lastFrame, stdin, unmount } = renderWide(<MouseProvider value={mouseManager}><App /></MouseProvider>);
    await settle();
    type(stdin, '/addmodel');
    await settle();
    stdin.write('\r');
    await new Promise((r) => setTimeout(r, 80));
    const f = lastFrame() ?? '';
    expect(f).toContain('添加模型');
    expect(f).toContain('[1/4]');
    // old behaviour pushed the step prompt into the chat log — must be gone
    expect(f).not.toContain('请输入模型名称');
    unmount();
  });

  it('rejects credential-bearing /addmodel text without sending it to the API', async () => {
    const { stdin, unmount } = renderWide(
      <MouseProvider value={mouseManager}><App /></MouseProvider>,
    );
    await settle();
    type(stdin, '/addmodel provider sk-never-send https://example.test alias');
    await settle();
    stdin.write('\r');
    await settle();

    expect(apiMocks.sendCommand).not.toHaveBeenCalled();
    expect(apiMocks.addModel).not.toHaveBeenCalled();
    expect(apiMocks.addMessage).toHaveBeenCalledWith(
      expect.objectContaining({ content: expect.stringContaining('secure wizard') }),
    );
    unmount();
  });

  it('wizard walks 4 steps, rejects a bad URL, then closes', async () => {
    const { lastFrame, stdin, unmount } = renderWide(<MouseProvider value={mouseManager}><App /></MouseProvider>);
    await settle();
    type(stdin, '/addmodel'); await settle(); stdin.write('\r'); await new Promise((r) => setTimeout(r, 60));
    // 1 -> 2
    type(stdin, 'gpt-4'); await settle(); stdin.write('\r'); await new Promise((r) => setTimeout(r, 60));
    expect((lastFrame() ?? '')).toContain('[2/4]');
    // 2 -> 3
    type(stdin, 'sk-1234567890abcd'); await settle(); stdin.write('\r'); await new Promise((r) => setTimeout(r, 60));
    expect((lastFrame() ?? '')).toContain('[3/4]');
    // bad url stays on step 3 and shows an error
    type(stdin, 'not-a-url'); await settle(); stdin.write('\r'); await new Promise((r) => setTimeout(r, 60));
    const bad = lastFrame() ?? '';
    expect(bad).toContain('[3/4]');
    expect(bad).toContain('必须使用 https://');
    expect(bad).not.toContain('not-a-url');
    // good url -> 4
    type(stdin, 'https://api.openai.com'); await settle(); stdin.write('\r'); await new Promise((r) => setTimeout(r, 60));
    expect((lastFrame() ?? '')).toContain('[4/4]');
    // nickname -> finish: wizard closes, normal input box returns
    type(stdin, 'mygpt'); await settle(); stdin.write('\r'); await new Promise((r) => setTimeout(r, 80));
    const done = lastFrame() ?? '';
    expect(done).not.toContain('添加模型');
    expect(done).toContain('Ready');
    expect(apiMocks.addModel).toHaveBeenCalledWith({
      providerModelId: 'gpt-4',
      apiKey: 'sk-1234567890abcd',
      baseUrl: 'https://api.openai.com',
      nickname: 'mygpt',
    });
    expect(apiMocks.sendCommand).not.toHaveBeenCalledWith(
      expect.stringContaining('sk-1234567890abcd'),
    );
    unmount();
  });
});
