import { describe, test, expect } from 'vitest';
import { render } from 'ink-testing-library';
import React from 'react';
import ChatPanel, { isFinalized } from './ChatPanel.js';
import type { Message } from '../types.js';

const userMsg = (id: string, content: string): Message => ({ id, role: 'user', content, timestamp: 1000 });
const asstMsg = (id: string, content: string, done = true): Message => ({ id, role: 'assistant', content, timestamp: 2000, elapsed: 1.2, done });
const thinking = (id: string, content: string, done = false): Message => ({ id, role: 'thinking', content, timestamp: Date.now(), ...(done ? { done: true, elapsed: 0.5 } as Partial<Message> : {}) });
const toolMsg = (id: string, status: 'running' | 'success' | 'error' | 'timeout'): Message => ({ id, role: 'tool', content: '', timestamp: 4000, toolName: 'bash', toolArgs: '', toolStatus: status });

describe('isFinalized (message split logic)', () => {
  test('assistant is finalized only after final while user/system are immediate', () => {
    expect(isFinalized(userMsg('u', 'hi'))).toBe(true);
    expect(isFinalized(asstMsg('a-live', 'hello', false))).toBe(false);
    expect(isFinalized(asstMsg('a-done', 'hello', true))).toBe(true);
    expect(isFinalized({ id: 's', role: 'system', content: 'x', timestamp: 1 })).toBe(true);
  });
  test('thinking is finalized only when done', () => {
    expect(isFinalized(thinking('t', '...', false))).toBe(false);
    expect(isFinalized({ ...thinking('live', 'streaming', false), live: true })).toBe(false);
    expect(isFinalized(thinking('t', '...', true))).toBe(true);
  });
  test('tool is finalized only when not running', () => {
    expect(isFinalized(toolMsg('t1', 'running'))).toBe(false);
    expect(isFinalized(toolMsg('t2', 'success'))).toBe(true);
    expect(isFinalized(toolMsg('t3', 'error'))).toBe(true);
    expect(isFinalized(toolMsg('t4', 'timeout'))).toBe(true);
  });
});

describe('ChatPanel flicker (Static) behavior', () => {
  test('live assistant updates stay visible while an earlier thinking message is active', () => {
    const { rerender, lastFrame } = render(
      <ChatPanel
        messages={[userMsg('u1', 'USERMARKER'), thinking('t1', 'thinking', false), asstMsg('a1', 'ALPHA')]}
        height={20}
        mode="build"
        expandThinking={true}
      />,
    );

    rerender(
      <ChatPanel
        messages={[userMsg('u1', 'USERMARKER'), thinking('t1', 'thinking', false), asstMsg('a1', 'ALPHABETA')]}
        height={20}
        mode="build"
        expandThinking={true}
      />,
    );

    expect(lastFrame()).toContain('ALPHABETA');
  });

  test('finalizing a turn commits thinking and the complete assistant in source order', () => {
    const { rerender, lastFrame } = render(
      <ChatPanel
        messages={[userMsg('u1', 'USERMARKER'), thinking('t1', 'THINK_ACTIVE', false), asstMsg('a1', 'ALPHA')]}
        height={20}
        mode="build"
        expandThinking={true}
      />,
    );

    rerender(
      <ChatPanel
        messages={[userMsg('u1', 'USERMARKER'), thinking('t1', 'THINK_DONE', true), asstMsg('a1', 'ALPHABETA')]}
        height={20}
        mode="build"
        expandThinking={true}
      />,
    );

    const frame = lastFrame() ?? '';
    expect(frame).toContain('Thought');
    // U3: expanded + done may recall body (OpenCode-like); no longer assert hidden
    expect(frame).toContain('THINK_DONE');
    expect(frame).toContain('ALPHABETA');
    expect(frame.indexOf('Thought')).toBeLessThan(frame.indexOf('ALPHABETA'));
  });

  test('resets Static after clear and keeps a replacement session live', () => {
    const { rerender, lastFrame } = render(
      <ChatPanel
        messages={[userMsg('old-u', 'OLD_USER'), thinking('old-t', 'OLD_DONE', true), asstMsg('old-a', 'OLD_ANSWER')]}
        height={20}
        mode="build"
        expandThinking={true}
      />,
    );

    rerender(<ChatPanel messages={[]} height={20} mode="build" expandThinking={true} />);
    rerender(
      <ChatPanel
        messages={[userMsg('new-u', 'NEW_USER'), thinking('new-t', 'NEW_ACTIVE'), asstMsg('new-a', 'ALPHA')]}
        height={20}
        mode="build"
        expandThinking={true}
      />,
    );
    rerender(
      <ChatPanel
        messages={[userMsg('new-u', 'NEW_USER'), thinking('new-t', 'NEW_ACTIVE'), asstMsg('new-a', 'ALPHABETA')]}
        height={20}
        mode="build"
        expandThinking={true}
      />,
    );

    expect(lastFrame()).toContain('ALPHABETA');
  });

  test('active thinking message updates live in dynamic region', () => {
    const finalized = [userMsg('u1', 'USERMARKER')];
    const { rerender, lastFrame } = render(<ChatPanel messages={[...finalized, thinking('t1', 'thinking-A')]} height={20} mode="build" expandThinking={true} />);
    expect(lastFrame()).toContain('thinking-A');
    rerender(<ChatPanel messages={[...finalized, thinking('t1', 'thinking-BUPDATED')]} height={20} mode="build" expandThinking={true} />);
    expect(lastFrame()).toContain('thinking-BUPDATED');
  });

  test('finalized messages render in Static region (above dynamic region)', () => {
    const finalized = [userMsg('u1', 'USERMARKER_STABLE'), asstMsg('a1', 'ASSTMARKER_STABLE')];
    const { lastFrame } = render(<ChatPanel messages={[...finalized, thinking('t1', 'tick-active')]} height={20} mode="build" expandThinking={true} />);
    const frame = lastFrame() ?? '';
    const userIdx = frame.indexOf('USERMARKER_STABLE');
    const asstIdx = frame.indexOf('ASSTMARKER_STABLE');
    const activeIdx = frame.indexOf('tick-active');
    expect(userIdx).toBeGreaterThanOrEqual(0);
    expect(asstIdx).toBeGreaterThanOrEqual(0);
    expect(activeIdx).toBeGreaterThanOrEqual(0);
    // finalized (user/asst) are ABOVE the dynamic region; active (thinking) is INSIDE it
    expect(userIdx).toBeLessThan(activeIdx);
    expect(asstIdx).toBeLessThan(activeIdx);
  });

  test('done thinking migrates to Static region above still-active thinking (no flicker regression)', () => {
    const finalized = [userMsg('u1', 'USERMARKER_STABLE')];
    // a done thinking (Static) and an active one (dynamic) at the same time
    const messages = [...finalized, thinking('t1', 'tick-done', true), thinking('t2', 'tick-active', false)];
    const { lastFrame } = render(<ChatPanel messages={messages} height={20} mode="build" expandThinking={true} />);
    const frame = lastFrame() ?? '';
    const summaryIdx = frame.indexOf('Thought');
    const doneIdx = frame.indexOf('tick-done');
    const activeIdx = frame.indexOf('tick-active');
    // U3: expanded recall shows done body; still above active thinking
    expect(doneIdx).toBeGreaterThanOrEqual(0);
    expect(summaryIdx).toBeGreaterThanOrEqual(0);
    expect(activeIdx).toBeGreaterThanOrEqual(0);
    expect(doneIdx).toBeLessThan(activeIdx);
  });

  test('welcome message shows when no messages', () => {
    const { lastFrame } = render(<ChatPanel messages={[]} height={20} mode="build" expandThinking={false} />);
    expect(lastFrame()).toContain('RxyCode');
  });
});
