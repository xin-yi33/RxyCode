import React from 'react';
import { render } from 'ink-testing-library';
import { describe, expect, test } from 'vitest';
import ChatPanel from './ChatPanel.js';
import type { Message } from '../types.js';

function message(id: number): Message {
  return {
    id: `m-${id}`,
    role: 'assistant',
    content: `history-message-${id}`,
    timestamp: 1_700_000_000_000 + id,
    done: true,
  };
}

describe('ChatPanel continuous history', () => {
  test('keeps the first and last message reachable in a long conversation', () => {
    const messages = Array.from({ length: 120 }, (_, index) => message(index));
    const { lastFrame } = render(
      <ChatPanel messages={messages} height={12} mode="build" expandThinking />,
    );
    const frame = lastFrame() ?? '';
    expect(frame).toContain('history-message-0');
    expect(frame).toContain('history-message-119');
    expect(frame).not.toContain('PgUp');
  });

  test('renders complete successful tool output', () => {
    const messages: Message[] = [{
      id: 'tool-1',
      role: 'tool',
      content: 'line-one\nline-two\nfinal-tool-line',
      timestamp: Date.now(),
      toolName: 'write_file',
      toolArgs: 'demo.txt',
      toolStatus: 'success',
      toolExitCode: 0,
    }];
    const { lastFrame } = render(
      <ChatPanel messages={messages} height={8} mode="build" expandThinking />,
    );
    const frame = lastFrame() ?? '';
    expect(frame).toContain('write_file');
    expect(frame).toContain('demo.txt');
    expect(frame).not.toContain('line-one');
    expect(frame).not.toContain('final-tool-line');
  });
});
