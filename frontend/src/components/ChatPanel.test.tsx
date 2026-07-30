import { describe, it, expect } from 'vitest';
import { render } from 'ink-testing-library';
import React from 'react';
import ChatPanel from './ChatPanel.js';

const base = { height: 40, mode: 'build' as const, expandThinking: false };

describe('ChatPanel', () => {
  it('shows welcome screen when there are no messages', () => {
    const { lastFrame } = render(<ChatPanel {...base} messages={[]} />);
    const f = lastFrame() ?? '';
    expect(f).toContain('RxyCode');
    expect(f).toContain('快捷键');
    expect(f).not.toContain('尚未配置模型');
  });

  it('shows no-model hint when needsModelSetup is true', () => {
    const { lastFrame } = render(<ChatPanel {...base} messages={[]} needsModelSetup />);
    expect(lastFrame() ?? '').toContain('尚未配置模型');
  });

  it('renders a user message', () => {
    const { lastFrame } = render(
      <ChatPanel {...base} messages={[{ id: '1', role: 'user', content: 'hello world', timestamp: Date.now() }] as any} />,
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('hello world');
  });

  it('renders an assistant message with markdown headings and bullets', () => {
    const { lastFrame } = render(
      <ChatPanel {...base} messages={[{ id: '1', role: 'assistant', content: '# Title\n- bullet', timestamp: Date.now() }] as any} />,
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('Title');
    expect(f).toContain('bullet');
  });

  it('expands thinking content when expandThinking is true', () => {
    const { lastFrame } = render(
      <ChatPanel {...base} expandThinking={true} messages={[{ id: '1', role: 'thinking', content: 'step A\nstep B', done: false, timestamp: Date.now() }] as any} />,
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('step A');
    expect(f).toContain('step B');
  });

  it('respects expandThinking=false even while streaming (问题5)', () => {
    // 旧行为 `!done || expanded` 在流式中强制展开，导致 Ctrl+T / /thinking
    // 关闭后看起来毫无变化；新契约：用户开关在任何时刻都生效。
    const { lastFrame } = render(
      <ChatPanel {...base} expandThinking={false} messages={[{ id: '1', role: 'thinking', content: 'step A\nstep B', done: false, live: true, timestamp: Date.now() }] as any} />,
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('Thought');
    expect(f).not.toContain('step A');
    expect(f).not.toContain('step B');
  });

  it('collapses thinking content after done when expandThinking is false', () => {
    const { lastFrame } = render(
      <ChatPanel {...base} expandThinking={false} messages={[{ id: '1', role: 'thinking', content: 'secret step', done: true, timestamp: Date.now() }] as any} />,
    );
    const f = lastFrame() ?? '';
    expect(f).not.toContain('secret step');
  });

  it('shows completed thinking content when expandThinking is true (U3 recall)', () => {
    const { lastFrame } = render(
      <ChatPanel {...base} expandThinking messages={[{
        id: 'thinking-complete',
        role: 'thinking',
        content: 'private-reasoning-line-1\nprivate-reasoning-line-2',
        done: true,
        elapsed: 1.2,
        timestamp: Date.now(),
      }] as any} />,
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('Thought');
    expect(f).toContain('private-reasoning-line-1');
    expect(f).toContain('private-reasoning-line-2');
  });

  it('keeps a long streaming assistant response inside a bounded tail preview', () => {
    const content = Array.from({ length: 80 }, (_, index) => `stream-line-${index}`).join('\n');
    const { lastFrame } = render(
      <ChatPanel {...base} height={18} messages={[{
        id: 'assistant-live',
        role: 'assistant',
        content,
        done: false,
        timestamp: Date.now(),
      }] as any} />,
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('stream-line-79');
    expect(f).not.toContain('stream-line-0');
    expect(f.split('\n').length).toBeLessThanOrEqual(18);
  });

  it('commits completed tool output as a bounded summary', () => {
    const content = Array.from({ length: 80 }, (_, index) => `tool-line-${index}`).join('\n');
    const { lastFrame } = render(
      <ChatPanel {...base} messages={[{
        id: 'tool-complete',
        role: 'tool',
        content,
        toolName: 'read',
        toolArgs: 'large-file.ts',
        toolStatus: 'success',
        timestamp: Date.now(),
      }] as any} />,
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('read');
    expect(f).toContain('large-file.ts');
    expect(f).not.toContain('tool-line-0');
    expect(f).not.toContain('tool-line-79');
  });

  it('does not commit failed tool output or error details into terminal history', () => {
    const leaked = 'private failure output '.repeat(100);
    const { lastFrame } = render(
      <ChatPanel {...base} messages={[{
        id: 'tool-error',
        role: 'tool',
        content: leaked,
        toolError: leaked,
        toolName: 'shell',
        toolArgs: 'failing-command',
        toolStatus: 'error',
        timestamp: Date.now(),
      }] as any} />,
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('shell');
    expect(f).toContain('error');
    expect(f).not.toContain('private failure output');
  });

  it('bounds a long single-line streaming assistant response by characters', () => {
    const content = `stream-start-${'x'.repeat(12000)}-stream-end`;
    const { lastFrame } = render(
      <ChatPanel {...base} height={18} messages={[{
        id: 'assistant-single-line',
        role: 'assistant',
        content,
        done: false,
        timestamp: Date.now(),
      }] as any} />,
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('stream-end');
    expect(f).not.toContain('stream-start');
    expect(f.length).toBeLessThan(4000);
  });
});
