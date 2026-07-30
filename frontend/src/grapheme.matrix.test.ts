import { describe, expect, test } from 'vitest';
import {
  clampToGraphemeBoundary,
  graphemeSpans,
  nextGraphemeBoundary,
  previousGraphemeBoundary,
} from './grapheme.js';

const SAMPLES: Array<{ label: string; value: string; segments?: string[] }> = [
  { label: 'ascii', value: 'hello', segments: ['h', 'e', 'l', 'l', 'o'] },
  { label: 'family emoji', value: 'A👨‍👩‍👧‍👦B', segments: ['A', '👨‍👩‍👧‍👦', 'B'] },
  { label: 'combining acute', value: 'e\u0301x', segments: ['e\u0301', 'x'] },
  { label: 'skin tone', value: '👍🏽ok', segments: ['👍🏽', 'o', 'k'] },
  { label: 'flag', value: '🇨🇳', segments: ['🇨🇳'] },
  { label: 'ZWJ sequence', value: '👨‍💻', segments: ['👨‍💻'] },
  { label: 'cjk', value: '中文测试', segments: ['中', '文', '测', '试'] },
  { label: 'mixed', value: 'a中🙂b', segments: ['a', '中', '🙂', 'b'] },
  { label: 'variation selector', value: '❤️', segments: ['❤️'] },
  { label: 'empty', value: '', segments: [] },
];

describe('graphemeSpans segment matrix', () => {
  for (const { label, value, segments } of SAMPLES) {
    test(`${label}`, () => {
      const spans = graphemeSpans(value);
      if (segments) {
        expect(spans.map((s) => s.segment)).toEqual(segments);
      }
      let reconstructed = '';
      for (const span of spans) {
        expect(span.start).toBeLessThanOrEqual(span.end);
        reconstructed += span.segment;
      }
      expect(reconstructed).toBe(value);
    });
  }
});

describe('boundary navigation sweep', () => {
  for (const { label, value } of SAMPLES) {
    if (!value) continue;
    for (let offset = 0; offset <= value.length; offset += 1) {
      test(`${label} offset=${offset}`, () => {
        const clamped = clampToGraphemeBoundary(value, offset);
        expect(clamped).toBeGreaterThanOrEqual(0);
        expect(clamped).toBeLessThanOrEqual(value.length);
        const prev = previousGraphemeBoundary(value, offset);
        const next = nextGraphemeBoundary(value, offset);
        expect(prev).toBeLessThanOrEqual(clamped);
        expect(next).toBeGreaterThanOrEqual(clamped);
      });
    }
  }
});

describe('next/previous round-trip', () => {
  for (const { label, value } of SAMPLES) {
    if (value.length < 2) continue;
    test(`${label} forward then backward`, () => {
      const forward = nextGraphemeBoundary(value, 0);
      expect(forward).toBeGreaterThan(0);
      const back = previousGraphemeBoundary(value, forward);
      expect(back).toBe(0);
    });
  }
});

describe('clamp never splits grapheme', () => {
  const offsets = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
  const emojiText = 'A👨‍👩‍👧‍👦B';
  for (const offset of offsets) {
    test(`clamp offset ${offset}`, () => {
      const clamped = clampToGraphemeBoundary(emojiText, offset);
      for (const span of graphemeSpans(emojiText)) {
        if (offset > span.start && offset < span.end) {
          expect(clamped).toBe(span.start);
        }
      }
    });
  }
});

describe('Win32 surrogate pairs', () => {
  const pairs = ['\uD83D\uDE00', '\uD83C\uDF0D', 'test\uD800'];
  for (const text of pairs) {
    test(`spans for ${JSON.stringify(text)}`, () => {
      const spans = graphemeSpans(text);
      expect(spans.length).toBeGreaterThanOrEqual(1);
    });
  }
});

describe('emoji modifier matrix', () => {
  const modifiers = ['\u{1F3FB}', '\u{1F3FC}', '\u{1F3FD}', '\u{1F3FE}', '\u{1F3FF}'];
  for (const mod of modifiers) {
    test(`👍${mod}`, () => {
      const value = `👍${mod}`;
      const spans = graphemeSpans(value);
      expect(spans.length).toBe(1);
      expect(spans[0].segment).toBe(value);
    });
  }
});

describe('combining mark clusters', () => {
  const clusters = [
    'a\u0300',
    'o\u0308',
    'n\u0303',
    'x\u0301\u0302',
  ];
  for (const cluster of clusters) {
    test(`cluster ${JSON.stringify(cluster)}`, () => {
      expect(graphemeSpans(cluster).length).toBeLessThanOrEqual(2);
    });
  }
});
