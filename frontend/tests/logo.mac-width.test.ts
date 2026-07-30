/**
 * W26 — automated Mac Terminal / iTerm display-width compatibility matrix.
 * Physical macOS hardware is not required; widths follow common Mac defaults.
 */
import { describe, expect, test } from 'vitest';
import stringWidth from 'string-width';
import {
  WORDMARK,
  WORDMARK_DISPLAY_WIDTH,
  padToDisplayWidth,
  centerLine,
} from '../src/logo.js';

/** Typical macOS Terminal.app and iTerm2 default widths. */
const MAC_TERMINAL_WIDTHS = [80, 100, 120, 132, 140] as const;

const MAC_GRAPHEME_SAMPLES = [
  '中文',
  '日本語',
  '한글',
  '🙂',
  '👨‍👩‍👧‍👦',
  'ＡＢＣ',
  '—',
] as const;

describe('macOS Terminal / iTerm width matrix (W26)', () => {
  for (const cols of MAC_TERMINAL_WIDTHS) {
    test(`WORDMARK centers within ${cols} cols (Mac default)`, () => {
      const rendered = WORDMARK.map((line) =>
        centerLine(padToDisplayWidth(line.replace(/ +$/, ''), WORDMARK_DISPLAY_WIDTH), cols),
      );
      for (const row of rendered) {
        expect(stringWidth(row)).toBeLessThanOrEqual(cols);
      }
      const leading = rendered.map((l) => l.match(/^( *)/)?.[1]?.length ?? 0);
      expect(new Set(leading).size).toBe(1);
    });
  }

  for (const sample of MAC_GRAPHEME_SAMPLES) {
    for (const cols of [80, 120, 132]) {
      test(`Mac grapheme "${sample}" in ${cols} cols`, () => {
        const centered = centerLine(sample, cols);
        expect(stringWidth(centered)).toBeLessThanOrEqual(cols);
      });
    }
  }
});
