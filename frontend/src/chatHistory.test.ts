import { describe, expect, it } from 'vitest';
import { isChatLoadedResponse, mapLoadedChatMessages } from './chatHistory.js';

describe('loaded chat history', () => {
  it('maps valid stored records to ordered UI messages', () => {
    expect(mapLoadedChatMessages([
      { role: 'user', content: 'question' },
      { role: 'assistant', content: 'answer' },
      { role: 'system', content: 'notice' },
    ], 1000)).toEqual([
      { id: 'loaded-1000-0', role: 'user', content: 'question', timestamp: 1000 },
      { id: 'loaded-1000-1', role: 'assistant', content: 'answer', timestamp: 1001, done: true },
      { id: 'loaded-1000-2', role: 'system', content: 'notice', timestamp: 1002 },
    ]);
  });

  it('rejects malformed responses and skips invalid records', () => {
    expect(isChatLoadedResponse({ action: 'chat_loaded', messages: [] })).toBe(true);
    expect(isChatLoadedResponse({ action: 'error', messages: [] })).toBe(false);
    expect(isChatLoadedResponse({ action: 'chat_loaded' })).toBe(false);
    expect(mapLoadedChatMessages([
      null,
      { role: 'developer', content: 'hidden' },
      { role: 'user', content: 42 },
      { role: 'assistant', content: '' },
    ], 2000)).toEqual([
      { id: 'loaded-2000-3', role: 'assistant', content: '', timestamp: 2003, done: true },
    ]);
  });

  it('restores every streamed role and complete tool metadata without truncation', () => {
    const stdout = 'start\n' + 'x'.repeat(1200) + '\nend';
    expect(mapLoadedChatMessages([
      { version: 1, id: 'think-1', run_id: 'run-1', role: 'thinking', content: 'full reasoning', timestamp: 10, done: true, live: false, elapsed: 1.5, stepIndex: 2, stepTotal: 3 },
      { version: 1, id: 'tool-1', run_id: 'run-1', role: 'tool', content: stdout, timestamp: 11, toolName: 'bash', toolArgs: '{"cmd":"test"}', toolStatus: 'cancelled', toolDuration: 0.75, toolExitCode: 130, toolStdout: stdout, toolError: 'cancelled' },
    ], 9000)).toEqual([
      { version: 1, id: 'think-1', runId: 'run-1', role: 'thinking', content: 'full reasoning', timestamp: 10, done: true, live: false, elapsed: 1.5, stepIndex: 2, stepTotal: 3 },
      { version: 1, id: 'tool-1', runId: 'run-1', role: 'tool', content: stdout, timestamp: 11, toolName: 'bash', toolArgs: '{"cmd":"test"}', toolStatus: 'cancelled', toolDuration: 0.75, toolExitCode: 130, toolStdout: stdout, toolError: 'cancelled' },
    ]);
  });
});
