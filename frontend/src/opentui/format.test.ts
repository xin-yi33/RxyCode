import { describe, expect, test } from 'vitest';
import {
  formatHeaderLine,
  formatInputHint,
  formatMessageLine,
  messageFg,
} from './format.js';
import type { Message, Mode } from '../types.js';

const ROLES: Message['role'][] = ['user', 'assistant', 'thinking', 'tool', 'system'];

describe('formatMessageLine role matrix', () => {
  for (const role of ROLES) {
    test(`formats ${role} messages`, () => {
      const msg: Message = {
        id: `fmt-${role}`,
        role,
        content: 'payload',
        timestamp: 1,
        ...(role === 'tool' ? { toolName: 'grep', toolStatus: 'success' as const } : {}),
      };
      const line = formatMessageLine(msg);
      expect(line.length).toBeGreaterThan(0);
      if (role === 'user') expect(line).toBe('> payload');
      if (role === 'assistant') expect(line).toBe('payload');
      if (role === 'thinking') expect(line).toBe('思考: payload');
      if (role === 'tool') expect(line).toBe('⚙ grep [success]');
      if (role === 'system') expect(line).toBe('• payload');
    });
  }
});

describe('formatMessageLine tool status matrix', () => {
  const statuses = ['running', 'success', 'error', 'timeout', 'cancelled'] as const;
  for (const toolStatus of statuses) {
    test(`tool status ${toolStatus}`, () => {
      const msg: Message = {
        id: 't',
        role: 'tool',
        content: 'out',
        timestamp: 1,
        toolName: 'bash',
        toolStatus,
      };
      expect(formatMessageLine(msg)).toBe(`⚙ bash [${toolStatus}]`);
    });
  }
});

describe('formatMessageLine tool name fallback', () => {
  test('missing toolName uses "tool"', () => {
    const msg: Message = { id: 't', role: 'tool', content: 'x', timestamp: 1 };
    expect(formatMessageLine(msg)).toBe('⚙ tool [running]');
  });
});

describe('formatHeaderLine mode matrix', () => {
  const modes: Mode[] = ['build', 'plan', 'compose'];
  const models = ['gpt-4', 'deepseek-v4-flash', 'claude-3', 'local-llm'];
  for (const mode of modes) {
    for (const model of models) {
      for (const thinkingLive of [false, true]) {
        test(`${mode}/${model}/thinking=${thinkingLive}`, () => {
          const line = formatHeaderLine(mode, model, thinkingLive);
          expect(line).toContain('RxyCode v1.2.0');
          expect(line).toContain(mode);
          expect(line).toContain(model);
          if (thinkingLive) expect(line).toContain('思考中');
          else expect(line).not.toContain('思考中');
        });
      }
    }
  }
});

describe('formatInputHint matrix', () => {
  for (const streaming of [false, true]) {
    test(`streaming=${streaming}`, () => {
      expect(formatInputHint(streaming)).toBe(streaming ? 'Processing...' : 'Ready');
    });
  }
});

describe('messageFg role colors', () => {
  const expected: Record<Message['role'], string> = {
    user: '#FFB6C1',
    assistant: '#cdd6f4',
    thinking: '#6c7086',
    tool: '#94e2d5',
    system: '#f9e2af',
  };
  for (const role of ROLES) {
    test(`${role} color`, () => {
      expect(messageFg(role)).toBe(expected[role]);
    });
  }
});

describe('formatMessageLine content edge cases', () => {
  const contents = ['', ' ', 'hello\nworld', '中文测试', '🙂 emoji', 'a'.repeat(200)];
  for (const content of contents) {
    for (const role of ['user', 'assistant'] as const) {
      test(`${role} with ${content.length} chars`, () => {
        const msg: Message = { id: 'e', role, content, timestamp: 1 };
        const line = formatMessageLine(msg);
        expect(line).toContain(content.trim() || content);
      });
    }
  }
});
