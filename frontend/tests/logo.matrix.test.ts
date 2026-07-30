import { describe, expect, test } from 'vitest';
import stringWidth from 'string-width';
import {
  centerLine,
  padToDisplayWidth,
  WORDMARK,
  WORDMARK_DISPLAY_WIDTH,
} from '../src/logo.js';

describe('padToDisplayWidth matrix', () => {
  const cases: Array<[string, number, number]> = [
    ['abc', 10, 10],
    ['', 5, 5],
    ['你好', 8, 8],
    ['🙂', 4, 4],
    ['A👨‍👩‍👧‍👦B', 12, 12],
    ['█', 3, 3],
    ['test', 4, 4],
    ['test', 3, 4],
    ['  spaced  ', 12, 12],
    ['\t', 4, 4],
  ];

  for (const [text, target, expectedWidth] of cases) {
    test(`"${text}" -> width ${expectedWidth}`, () => {
      const padded = padToDisplayWidth(text, target);
      expect(stringWidth(padded)).toBe(expectedWidth);
      expect(padded.startsWith(text)).toBe(true);
    });
  }

  for (let target = 1; target <= 80; target += 1) {
    test(`ascii fill at target=${target}`, () => {
      const padded = padToDisplayWidth('x', target);
      expect(stringWidth(padded)).toBe(Math.max(stringWidth('x'), target));
    });
  }

  const cjkSamples = ['中', '日本語', '한글', '繁體', '简体'];
  for (const sample of cjkSamples) {
    for (const target of [4, 8, 12, 16, 20]) {
      test(`CJK "${sample}" pad to ${target}`, () => {
        const padded = padToDisplayWidth(sample, target);
        expect(stringWidth(padded)).toBeGreaterThanOrEqual(stringWidth(sample));
        expect(stringWidth(padded)).toBe(Math.max(stringWidth(sample), target));
      });
    }
  }

  const emojiSamples = ['🙂', '👍', '🎉', '🇨🇳', '👨‍👩‍👧‍👦'];
  for (const emoji of emojiSamples) {
    for (const target of [2, 4, 6, 8, 10]) {
      test(`emoji "${emoji}" pad to ${target}`, () => {
        const padded = padToDisplayWidth(emoji, target);
        expect(stringWidth(padded)).toBe(Math.max(stringWidth(emoji), target));
      });
    }
  }
});

describe('centerLine display-width matrix', () => {
  const terminals = [40, 60, 80, 100, 120, 132];
  const samples = [
    'abc',
    'hello world',
    '中文居中',
    '🙂',
    'A👨‍👩‍👧‍👦B',
    WORDMARK[0].replace(/ +$/, ''),
  ];

  for (const width of terminals) {
    for (const sample of samples) {
      test(`center "${sample.slice(0, 12)}..." in ${width} cols`, () => {
        const centered = centerLine(sample, width);
        const sw = stringWidth(centered);
        const sampleW = stringWidth(sample);
        if (sampleW >= width) {
          expect(centered).toBe(sample);
        } else {
          expect(sw).toBeLessThanOrEqual(width);
          const pad = Math.floor((width - sampleW) / 2);
          expect(centered.startsWith(' '.repeat(pad))).toBe(true);
        }
      });
    }
  }

  for (let width = 5; width <= 100; width += 5) {
    test(`symmetric padding at width=${width}`, () => {
      const text = 'test';
      const centered = centerLine(text, width);
      if (stringWidth(text) < width) {
        const leading = centered.match(/^( *)/)?.[1]?.length ?? 0;
        expect(leading).toBe(Math.floor((width - stringWidth(text)) / 2));
      }
    });
  }
});

describe('WORDMARK display width invariants', () => {
  for (let i = 0; i < WORDMARK.length; i += 1) {
    test(`line ${i} padded width equals WORDMARK_DISPLAY_WIDTH`, () => {
      const trimmed = WORDMARK[i].replace(/ +$/, '');
      const padded = padToDisplayWidth(trimmed, WORDMARK_DISPLAY_WIDTH);
      expect(stringWidth(padded)).toBe(WORDMARK_DISPLAY_WIDTH);
    });
  }

  for (const cols of [80, 100, 120, 132]) {
    test(`padded lines center consistently at ${cols} cols`, () => {
      const centered = WORDMARK.map((line) =>
        centerLine(padToDisplayWidth(line.replace(/ +$/, ''), WORDMARK_DISPLAY_WIDTH), cols),
      );
      const leading = centered.map((l) => l.match(/^( *)/)?.[1]?.length ?? 0);
      expect(new Set(leading).size).toBe(1);
    });
  }
});

describe('Win32 / mixed-width edge cases', () => {
  const mixed = [
    ['\uFF01全角!', 20],
    ['ＡＢＣabc', 15],
    ['\u200B', 4],
    ['\uFEFF', 4],
    ['\u00A0nbsp', 10],
  ] as const;

  for (const [text, target] of mixed) {
    test(`mixed "${String(text).slice(0, 8)}" target=${target}`, () => {
      const padded = padToDisplayWidth(text, target);
      expect(stringWidth(padded)).toBeGreaterThanOrEqual(stringWidth(text));
    });
    test(`center mixed "${String(text).slice(0, 8)}" in 80 cols`, () => {
      const centered = centerLine(text, 80);
      expect(stringWidth(centered)).toBeLessThanOrEqual(80);
    });
  }
});
