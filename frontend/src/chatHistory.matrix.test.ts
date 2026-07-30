import { describe, expect, it } from 'vitest';
import { isChatLoadedResponse, mapLoadedChatMessages } from './chatHistory.js';
import type { Message } from './types.js';

const ROLES = ['user', 'assistant', 'tool', 'thinking', 'system'] as const;
const TOOL_STATUSES = ['running', 'success', 'error', 'timeout', 'cancelled'] as const;

describe('isChatLoadedResponse matrix', () => {
  const valid = [
    { action: 'chat_loaded', messages: [] },
    { action: 'chat_loaded', messages: [{ role: 'user', content: 'hi' }] },
    { action: 'chat_loaded', messages: [], schema_version: 1 },
  ];
  const invalid = [
    null,
    undefined,
    {},
    { action: 'error', messages: [] },
    { action: 'chat_loaded' },
    { action: 'chat_loaded', messages: 'not-array' },
    { messages: [] },
  ];

  for (const v of valid) {
    it(`accepts ${JSON.stringify(v).slice(0, 40)}`, () => {
      expect(isChatLoadedResponse(v)).toBe(true);
    });
  }
  for (const v of invalid) {
    it(`rejects ${JSON.stringify(v)}`, () => {
      expect(isChatLoadedResponse(v)).toBe(false);
    });
  }
});

describe('mapLoadedChatMessages role round-trip', () => {
  for (const role of ROLES) {
    it(`restores ${role}`, () => {
      const base = { role, content: `${role}-content`, timestamp: 100 };
      const extra: Record<string, unknown> = { ...base };
      if (role === 'tool') {
        extra.toolName = 'read';
        extra.toolStatus = 'success';
        extra.toolArgs = '{}';
      }
      if (role === 'thinking') {
        extra.done = true;
        extra.live = false;
        extra.stepIndex = 1;
        extra.stepTotal = 3;
      }
      const mapped = mapLoadedChatMessages([extra], 5000);
      expect(mapped.length).toBe(1);
      expect(mapped[0].role).toBe(role);
      expect(mapped[0].content).toBe(`${role}-content`);
    });
  }
});

describe('mapLoadedChatMessages tool status matrix', () => {
  for (const toolStatus of TOOL_STATUSES) {
    it(`toolStatus=${toolStatus}`, () => {
      const mapped = mapLoadedChatMessages([{
        role: 'tool',
        content: 'out',
        toolName: 'bash',
        toolStatus,
        toolDuration: 1.5,
        toolExitCode: toolStatus === 'success' ? 0 : 1,
      }], 100);
      expect(mapped[0].toolStatus).toBe(toolStatus);
    });
  }
});

describe('mapLoadedChatMessages skips invalid records', () => {
  const invalidRecords = [
    null,
    undefined,
    'string',
    42,
    {},
    { role: 'developer', content: 'x' },
    { role: 'user', content: 123 },
    { role: 'assistant' },
    { content: 'no role' },
  ];

  for (const record of invalidRecords) {
    it(`skips ${JSON.stringify(record)}`, () => {
      expect(mapLoadedChatMessages([record], 100)).toEqual([]);
    });
  }
});

describe('mapLoadedChatMessages id/timestamp assignment', () => {
  it('uses provided id and timestamp', () => {
    const mapped = mapLoadedChatMessages([{
      id: 'custom-id',
      role: 'user',
      content: 'hi',
      timestamp: 999,
    }], 100);
    expect(mapped[0].id).toBe('custom-id');
    expect(mapped[0].timestamp).toBe(999);
  });

  it('generates id and timestamp when missing', () => {
    const mapped = mapLoadedChatMessages([
      { role: 'user', content: 'a' },
      { role: 'user', content: 'b' },
    ], 2000);
    expect(mapped[0].id).toBe('loaded-2000-0');
    expect(mapped[1].id).toBe('loaded-2000-1');
    expect(mapped[1].timestamp).toBe(2001);
  });
});

describe('assistant always marked done', () => {
  for (const done of [undefined, false, true]) {
    it(`done=${String(done)}`, () => {
      const mapped = mapLoadedChatMessages([{
        role: 'assistant',
        content: 'answer',
        ...(done !== undefined ? { done } : {}),
      }], 100);
      expect(mapped[0].done).toBe(true);
    });
  }
});

describe('thinking metadata round-trip', () => {
  const cases = [
    { done: true, live: false, elapsed: 2.5, stepIndex: 2, stepTotal: 5 },
    { done: false, live: true },
    { done: true, live: false, elapsed: 0 },
  ];
  for (const meta of cases) {
    it(JSON.stringify(meta), () => {
      const mapped = mapLoadedChatMessages([{
        role: 'thinking',
        content: 'reason',
        ...meta,
      }], 100);
      expect(mapped[0]).toMatchObject(meta);
    });
  }
});

describe('full conversation round-trip', () => {
  const conversation: unknown[] = [
    { role: 'user', content: 'Q1' },
    { role: 'thinking', content: 'T1', done: true },
    { role: 'tool', content: 'out', toolName: 'grep', toolStatus: 'success' },
    { role: 'assistant', content: 'A1' },
    { role: 'system', content: 'cleared' },
    { role: 'user', content: 'Q2' },
    { role: 'assistant', content: 'A2' },
  ];

  it('preserves order and count', () => {
    const mapped = mapLoadedChatMessages(conversation, 3000);
    expect(mapped.map((m) => m.role)).toEqual([
      'user', 'thinking', 'tool', 'assistant', 'system', 'user', 'assistant',
    ]);
    expect(mapped.length).toBe(7);
  });
});

describe('run_id and version passthrough', () => {
  it('maps run_id to runId', () => {
    const mapped = mapLoadedChatMessages([{
      role: 'thinking',
      content: 'x',
      run_id: 'run-abc',
      version: 2,
    }], 100);
    expect(mapped[0].runId).toBe('run-abc');
    expect(mapped[0].version).toBe(2);
  });
});

describe('invalid toolStatus ignored', () => {
  const bad = ['pending', 'unknown', ''];
  for (const toolStatus of bad) {
    it(`ignores "${toolStatus}"`, () => {
      const mapped = mapLoadedChatMessages([{
        role: 'tool',
        content: 'x',
        toolStatus,
      }], 100) as Message[];
      expect(mapped[0].toolStatus).toBeUndefined();
    });
  }
});
