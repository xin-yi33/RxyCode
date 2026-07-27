import { describe, expect, it } from 'vitest';
import { isSendBlocked, resolveFinalContent, settleActiveMessages } from './useApi.js';
import type { Message } from '../types.js';

describe('isSendBlocked matrix', () => {
  for (const streaming of [false, true]) {
    it(`streaming=${streaming}`, () => {
      expect(isSendBlocked(streaming)).toBe(streaming);
    });
  }
});

describe('resolveFinalContent matrix', () => {
  const cases: Array<[string, string | undefined, string]> = [
    ['tokens', undefined, 'tokens'],
    ['tokens', 'final', 'final'],
    ['', 'final', 'final'],
    ['draft', '', ''],
    ['long output', 'authoritative', 'authoritative'],
  ];

  for (const [accumulated, finalText, expected] of cases) {
    it(`${accumulated.slice(0, 10)} + ${String(finalText).slice(0, 10)}`, () => {
      expect(resolveFinalContent(accumulated, finalText)).toBe(expected);
    });
  }
});

describe('settleActiveMessages status matrix', () => {
  const statuses = ['error', 'timeout', 'cancelled'] as const;

  for (const toolStatus of statuses) {
    it(`settles with toolStatus=${toolStatus}`, () => {
      const messages: Message[] = [
        { id: 'a', role: 'assistant', content: 'partial', timestamp: 1, done: false },
        { id: 't', role: 'thinking', content: 'r', timestamp: 2, done: false, live: true },
        { id: 'x', role: 'tool', content: 'out', timestamp: 3, toolStatus: 'running' },
        { id: 'u', role: 'user', content: 'q', timestamp: 4 },
      ];
      const settled = settleActiveMessages(messages, toolStatus);
      expect(settled[0].done).toBe(true);
      expect(settled[1]).toMatchObject({ done: true, live: false });
      expect(settled[2].toolStatus).toBe(toolStatus);
      expect(settled[3]).toBe(messages[3]);
    });
  }
});

describe('settleActiveMessages no-op when already settled', () => {
  const settled: Message[] = [
    { id: 'a', role: 'assistant', content: 'done', timestamp: 1, done: true },
    { id: 'u', role: 'user', content: 'q', timestamp: 2 },
  ];
  it('returns same reference', () => {
    expect(settleActiveMessages(settled, 'error')).toBe(settled);
  });
});

describe('settleActiveMessages partial active', () => {
  const cases: Array<{ role: Message['role']; active: boolean }> = [
    { role: 'assistant', active: true },
    { role: 'thinking', active: true },
    { role: 'tool', active: true },
  ];

  for (const { role } of cases) {
    it(`only settles ${role}`, () => {
      const base: Message = {
        id: 'm',
        role,
        content: 'x',
        timestamp: 1,
      };
      if (role === 'assistant') Object.assign(base, { done: false });
      if (role === 'thinking') Object.assign(base, { done: false, live: true });
      if (role === 'tool') Object.assign(base, { toolStatus: 'running' as const });

      const other: Message = { id: 'u', role: 'user', content: 'q', timestamp: 2 };
      const result = settleActiveMessages([base, other], 'error');
      expect(result.length).toBe(2);
    });
  }
});
