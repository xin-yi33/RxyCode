import { describe, expect, it } from 'vitest';
import {
  formatUserFacingStreamError,
  toUserFacingError,
} from './userFacingErrors.js';

const MSG_BUILD = '构建流程未完成，部分步骤未通过验证。请查看任务详情后重试。';
const MSG_GROUNDING = '最终回答未能通过校验，内容与已验证结果不一致。请重试或简化任务。';
const MSG_TOOL = '工具执行中断，未能完成所需操作。请重试。';
const MSG_TIMEOUT = '请求超时，请稍后重试。';
const MSG_CANCELLED = '操作已取消。';
const MSG_DEFAULT = '处理未完成，请重试。';

const FORBIDDEN = /synthesizer|claim\s*manifest|grounded\s*claims?/i;

const GROUNDING_MARKERS = [
  'grounded claim',
  'claim manifest',
  'synthesis manifest',
  'synthesizer',
  'grounding failed',
  'verified synthesis',
  'verbatim source',
];

describe('toUserFacingError mapping table', () => {
  const cases: Array<[string, string]> = [
    ['', MSG_DEFAULT],
    ['   ', MSG_DEFAULT],
    ['cancelled', MSG_CANCELLED],
    ['CancelledError: user abort', MSG_CANCELLED],
    ['cancel requested by user', MSG_CANCELLED],
    ['request timeout', MSG_TIMEOUT],
    ['Connection timed out', MSG_TIMEOUT],
    ['[evidence failed: Tool bash did not complete: failed]', MSG_TOOL],
    ['tool xyz did not complete within limit', MSG_TOOL],
    ['[Build incomplete: Task not verified: deploy (failed)]', MSG_BUILD],
    ['[Build incomplete: anything]', MSG_BUILD],
    ...GROUNDING_MARKERS.map((m) => [`Error: ${m} detected`, MSG_GROUNDING] as [string, string]),
    ...GROUNDING_MARKERS.map((m) => [`[Build incomplete: ${m}]`, MSG_GROUNDING] as [string, string]),
    ['random internal failure', MSG_DEFAULT],
    ['null', MSG_DEFAULT],
  ];

  for (const [raw, expected] of cases) {
    it(`maps ${JSON.stringify(raw.slice(0, 40))} -> friendly`, () => {
      const friendly = toUserFacingError(raw);
      expect(friendly).toBe(expected);
      expect(FORBIDDEN.test(friendly)).toBe(false);
    });
  }
});

describe('formatUserFacingStreamError prefix table', () => {
  const inputs = [
    '[Build incomplete: Synthesizer produced no grounded claims]',
    '[evidence failed: Tool read did not complete]',
    'timeout after 30s',
    'cancelled',
    'unknown xyz',
    '',
  ];

  for (const input of inputs) {
    it(`Error: prefix for ${JSON.stringify(input.slice(0, 30))}`, () => {
      const formatted = formatUserFacingStreamError(input);
      expect(formatted.startsWith('Error: ')).toBe(true);
      expect(FORBIDDEN.test(formatted)).toBe(false);
    });
  }
});

describe('grounding marker case insensitivity', () => {
  for (const marker of GROUNDING_MARKERS) {
    for (const variant of [marker, marker.toUpperCase(), `Mixed ${marker}`]) {
      it(`detects ${variant.slice(0, 30)}`, () => {
        expect(toUserFacingError(variant)).toBe(MSG_GROUNDING);
      });
    }
  }
});

describe('cancel/timeout boundary cases', () => {
  const cancelCases = [
    'cancel',
    'cancelled',
    'CANCELLED',
    'CancelError',
    'cancelled by user',
    'operation cancel now',
  ];
  const timeoutCases = [
    'timeout',
    'TIMEOUT',
    'request timed out',
    'ETIMEDOUT',
    'deadline exceeded timeout',
  ];

  for (const c of cancelCases) {
    it(`cancel variant: ${c}`, () => {
      const result = toUserFacingError(c);
      expect([MSG_CANCELLED, MSG_DEFAULT]).toContain(result);
    });
  }

  for (const t of timeoutCases) {
    it(`timeout variant: ${t}`, () => {
      const result = toUserFacingError(t);
      if (t === 'ETIMEDOUT') {
        expect(result).toBe(MSG_DEFAULT);
      } else {
        expect(result).toBe(MSG_TIMEOUT);
      }
    });
  }
});

describe('stream error never leaks jargon', () => {
  const jargonInputs = [
    'synthesizer failed',
    'claim manifest empty',
    'grounded claims missing',
    '[Build incomplete: verified synthesis failed]',
  ];

  for (const input of jargonInputs) {
    it(`scrubs ${input}`, () => {
      const out = formatUserFacingStreamError(input);
      expect(FORBIDDEN.test(out)).toBe(false);
      expect(out).not.toMatch(/synthesizer|claim manifest|grounded claim/i);
    });
  }
});
