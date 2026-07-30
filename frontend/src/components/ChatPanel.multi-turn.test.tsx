import { describe, test, expect } from 'vitest';
import { render } from 'ink-testing-library';
import React from 'react';
import ChatPanel, { isFinalized } from './ChatPanel.js';
import type { Message } from '../types.js';

const mkUser = (id: string, content: string): Message => ({ id, role: 'user', content, timestamp: 1000 });
const mkAsst = (id: string, content: string): Message => ({ id, role: 'assistant', content, timestamp: 2000, elapsed: 1.2, done: true });
const mkThinking = (id: string, content: string, done = false): Message => ({ id, role: 'thinking', content, timestamp: Date.now(), ...(done ? { done: true, elapsed: 0.5 } as Partial<Message> : {}) });
const mkTool = (id: string, status: 'running' | 'success' | 'error' | 'timeout', content = ''): Message => ({ id, role: 'tool', content, timestamp: 4000, toolName: 'bash', toolArgs: '', toolStatus: status });

describe('Multi-turn conversation flicker tests', () => {
  test('committedCount grows monotonically across turns', () => {
    // Turn 1: user + thinking(active)
    const msgs1 = [mkUser('u1', 'hello'), mkThinking('t1', 'analyzing', false)];
    const { rerender, lastFrame } = render(<ChatPanel messages={msgs1} height={30} mode="build" expandThinking={true} />);
    let frame = lastFrame() ?? '';
    expect(frame).toContain('hello');
    expect(frame).toContain('analyzing');

    // Turn 1 complete: thinking done + assistant reply
    const msgs2 = [mkUser('u1', 'hello'), mkThinking('t1', 'analyzing', true), mkAsst('a1', 'Hi there')];
    rerender(<ChatPanel messages={msgs2} height={30} mode="build" expandThinking={true} />);
    frame = lastFrame() ?? '';
    expect(frame).toContain('hello');
    expect(frame).toContain('Hi there');

    // Turn 2: new user + thinking(active)
    const msgs3 = [...msgs2, mkUser('u2', 'what is 2+2'), mkThinking('t2', 'computing', false)];
    rerender(<ChatPanel messages={msgs3} height={30} mode="build" expandThinking={true} />);
    frame = lastFrame() ?? '';
    expect(frame).toContain('hello');
    expect(frame).toContain('Hi there');
    expect(frame).toContain('what is 2+2');
    expect(frame).toContain('computing');

    // Turn 2 complete
    const msgs4 = [...msgs3.slice(0, -1), mkThinking('t2', 'computing', true), mkAsst('a2', '4')];
    rerender(<ChatPanel messages={msgs4} height={30} mode="build" expandThinking={true} />);
    frame = lastFrame() ?? '';
    expect(frame).toContain('hello');
    expect(frame).toContain('Hi there');
    expect(frame).toContain('what is 2+2');
    expect(frame).toContain('4');
  });

  test('tool message transitions from running to success without flicker', () => {
    const base = [mkUser('u1', 'run ls'), mkThinking('t1', 'calling tool', true)];
    const { rerender, lastFrame } = render(<ChatPanel messages={[...base, mkTool('tool1', 'running')]} height={30} mode="build" expandThinking={true} />);
    let frame = lastFrame() ?? '';
    expect(frame).toContain('run ls');

    // Tool completes
    rerender(<ChatPanel messages={[...base, mkTool('tool1', 'success', 'file1.py')]} height={30} mode="build" expandThinking={true} />);
    frame = lastFrame() ?? '';
    expect(frame).toContain('run ls');
    expect(frame).toContain('bash');
    expect(frame).not.toContain('file1.py');

    // Assistant response added
    rerender(<ChatPanel messages={[...base, mkTool('tool1', 'success', 'file1.py'), mkAsst('a1', 'Found 1 file')]} height={30} mode="build" expandThinking={true} />);
    frame = lastFrame() ?? '';
    expect(frame).toContain('Found 1 file');
  });

  test('multiple rapid thinking updates do not cause content loss', () => {
    const base = [mkUser('u1', 'test')];
    const { rerender, lastFrame } = render(<ChatPanel messages={[...base, mkThinking('t1', 'step 1', false)]} height={30} mode="build" expandThinking={true} />);

    // Rapid updates
    for (let i = 2; i <= 10; i++) {
      rerender(<ChatPanel messages={[...base, mkThinking('t1', 'step ' + i, false)]} height={30} mode="build" expandThinking={true} />);
    }
    const frame = lastFrame() ?? '';
    expect(frame).toContain('step 10');
    expect(frame).toContain('test');
  });

  test('clear with key remount flushes old messages', () => {
    // In production, App.tsx changes the key prop on /clear, which forces React
    // to remount ChatPanel, flushing Ink <Static>. ink-testing-library's rerender
    // doesn't simulate remount, so we use separate render() calls to verify.
    const { lastFrame: frame1 } = render(<ChatPanel key={0} messages={[mkUser('u1', 'first'), mkAsst('a1', 'reply1')]} height={30} mode="build" expandThinking={true} />);
    expect(frame1()).toContain('first');
    expect(frame1()).toContain('reply1');

    // Simulate remount after /clear: new render() = new component instance
    const { lastFrame: frame2 } = render(<ChatPanel key={1} messages={[]} height={30} mode="build" expandThinking={true} />);
    const clearedFrame = frame2() ?? '';
    expect(clearedFrame).toContain('RxyCode');
    expect(clearedFrame).not.toContain('first');
    expect(clearedFrame).not.toContain('reply1');

    // New conversation after clear
    const { lastFrame: frame3 } = render(<ChatPanel key={1} messages={[mkUser('u2', 'second'), mkAsst('a2', 'reply2')]} height={30} mode="build" expandThinking={true} />);
    expect(frame3()).toContain('second');
    expect(frame3()).toContain('reply2');
    expect(frame3()).not.toContain('first');
  });

  test('all 5 capability lines shown in welcome', () => {
    const { lastFrame } = render(<ChatPanel messages={[]} height={30} mode="build" expandThinking={false} />);
    const frame = lastFrame() ?? '';
    expect(frame).toContain('代码开发');
    expect(frame).toContain('文件操作');
    expect(frame).toContain('项目管理');
    expect(frame).toContain('问题排查');
    expect(frame).toContain('研究分析');
  });
});

