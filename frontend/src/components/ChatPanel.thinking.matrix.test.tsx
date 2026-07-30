import { describe, it, expect } from 'vitest';
import { render } from 'ink-testing-library';
import React from 'react';
import ChatPanel from './ChatPanel.js';

const THINKING_MARKER = 'private-reasoning-marker-line';
const base = { height: 40, mode: 'build' as const };

type MatrixCase = {
  expandThinking: boolean;
  done: boolean;
  live?: boolean;
  expectSecret: boolean;
  label: string;
};

const MATRIX: MatrixCase[] = [];
for (const expandThinking of [false, true]) {
  for (const done of [false, true]) {
    for (const live of [undefined, false, true]) {
      if (!done && live === undefined) continue;
      const expectSecret = expandThinking;
      MATRIX.push({
        expandThinking,
        done,
        live,
        expectSecret,
        label: `expand=${expandThinking} done=${done} live=${live ?? 'unset'}`,
      });
    }
  }
}

describe('ChatPanel thinking expand/collapse/done recall matrix', () => {
  for (const { expandThinking, done, live, expectSecret, label } of MATRIX) {
    it(label, () => {
      const { lastFrame } = render(
        <ChatPanel
          {...base}
          expandThinking={expandThinking}
          messages={[{
            id: 'think-1',
            role: 'thinking',
            content: `${THINKING_MARKER}\nsecond line`,
            done,
            ...(live !== undefined ? { live } : {}),
            timestamp: Date.now(),
          }] as any}
        />,
      );
      const f = lastFrame() ?? '';
      expect(f).toContain('Thought');
      if (expectSecret) {
        expect(f).toContain(THINKING_MARKER);
      } else {
        expect(f).not.toContain(THINKING_MARKER);
      }
    });
  }
});

describe('ChatPanel thinking U3 recall (completed + expanded)', () => {
  for (const elapsed of [0, 0.5, 1.2, 10]) {
    it(`elapsed=${elapsed}s shows content when expanded`, () => {
      const { lastFrame } = render(
        <ChatPanel
          {...base}
          expandThinking
          messages={[{
            id: 'think-done',
            role: 'thinking',
            content: THINKING_MARKER,
            done: true,
            elapsed,
            timestamp: Date.now(),
          }] as any}
        />,
      );
      expect(lastFrame() ?? '').toContain(THINKING_MARKER);
    });
  }
});

describe('ChatPanel thinking collapse after done (问题5)', () => {
  for (const live of [false, true, undefined]) {
    it(`done=true live=${String(live)} collapsed when expand=false`, () => {
      const { lastFrame } = render(
        <ChatPanel
          {...base}
          expandThinking={false}
          messages={[{
            id: 't',
            role: 'thinking',
            content: THINKING_MARKER,
            done: true,
            ...(live !== undefined ? { live } : {}),
            timestamp: Date.now(),
          }] as any}
        />,
      );
      expect(lastFrame() ?? '').not.toContain(THINKING_MARKER);
    });
  }
});

describe('ChatPanel streaming respects expandThinking=false', () => {
  for (const live of [true, false]) {
    it(`live=${live} hides content when collapsed`, () => {
      const { lastFrame } = render(
        <ChatPanel
          {...base}
          expandThinking={false}
          messages={[{
            id: 't',
            role: 'thinking',
            content: THINKING_MARKER,
            done: false,
            live,
            timestamp: Date.now(),
          }] as any}
        />,
      );
      expect(lastFrame() ?? '').not.toContain(THINKING_MARKER);
    });
  }
});

describe('ChatPanel multiple thinking messages', () => {
  it('each respects expandThinking independently', () => {
    const { lastFrame } = render(
      <ChatPanel
        {...base}
        expandThinking
        messages={[
          { id: '1', role: 'thinking', content: 'visible-1', done: true, timestamp: 1 },
          { id: '2', role: 'thinking', content: 'visible-2', done: true, timestamp: 2 },
        ] as any}
      />,
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('visible-1');
    expect(f).toContain('visible-2');
  });
});
