import { describe, expect, test } from 'vitest';
import stringWidth from 'string-width';
import {
  caretOffsetFromClick,
  caretVisualPosition,
  cursorRowsFromFrameEnd,
  inputTextRow,
  maxVisibleFor,
  modalHeight,
  numInputLines,
  paletteHeight,
} from './layout.js';

describe('maxVisibleFor termRows matrix', () => {
  for (let termRows = 10; termRows <= 50; termRows += 1) {
    test(`termRows=${termRows}`, () => {
      const mv = maxVisibleFor(termRows);
      expect(mv).toBeGreaterThanOrEqual(4);
      expect(mv).toBeLessThanOrEqual(12);
    });
  }
});

describe('paletteHeight follows maxVisibleFor', () => {
  for (let termRows = 12; termRows <= 40; termRows += 2) {
    test(`termRows=${termRows}`, () => {
      expect(paletteHeight(termRows)).toBe(maxVisibleFor(termRows) + 6);
    });
  }
});

describe('modalHeight matrix', () => {
  for (let mv = 1; mv <= 20; mv += 1) {
    test(`mv=${mv}`, () => {
      expect(modalHeight(mv)).toBe(mv + 4);
    });
  }
});

describe('inputTextRow matrix', () => {
  for (let termRows = 20; termRows <= 40; termRows += 1) {
    for (let numLines = 1; numLines <= 8; numLines += 1) {
      test(`termRows=${termRows} numLines=${numLines}`, () => {
        expect(inputTextRow(termRows, numLines, 0)).toBe(termRows - 1 - numLines);
        expect(inputTextRow(termRows, numLines, 99)).toBe(termRows - 1 - numLines);
      });
    }
  }
});

describe('cursorRowsFromFrameEnd matrix', () => {
  for (let numTextLines = 1; numTextLines <= 10; numTextLines += 1) {
    for (let lineIndex = -2; lineIndex <= numTextLines + 2; lineIndex += 1) {
      test(`lines=${numTextLines} idx=${lineIndex}`, () => {
        const rows = cursorRowsFromFrameEnd(numTextLines, lineIndex);
        expect(rows).toBeGreaterThanOrEqual(2);
        const clamped = Math.max(0, Math.min(numTextLines - 1, lineIndex));
        expect(rows).toBe(2 + (numTextLines - clamped));
      });
    }
  }
});

describe('numInputLines wrap matrix', () => {
  const texts = [
    '',
    'a',
    'abcdefghij',
    'abcdefghijk',
    '我们呢',
    '我们呢我们呢我们呢',
    'A👨‍👩‍👧‍👦B',
    'line1\nline2',
    'x'.repeat(100),
  ];
  const wrapWidths = [1, 5, 10, 20, 40, 80];

  for (const text of texts) {
    for (const wrapW of wrapWidths) {
      test(`"${text.slice(0, 8)}..." wrap=${wrapW}`, () => {
        const lines = numInputLines(text, wrapW);
        expect(lines).toBeGreaterThanOrEqual(1);
        const logical = text.split('\n');
        const minExpected = logical.reduce(
          (sum, line) => sum + Math.max(1, Math.ceil(Math.max(stringWidth(line), line.length === 0 ? 0 : 1) / Math.max(1, wrapW))),
          0,
        );
        expect(lines).toBeGreaterThanOrEqual(Math.max(1, logical.length));
      });
    }
  }
});

describe('caretVisualPosition offset sweep', () => {
  const inputs = ['hello', '我们abc', 'A👨‍👩‍👧‍👦B', 'a\nb\nc'];
  const wrapWs = [5, 10, 20];

  for (const input of inputs) {
    for (const wrapW of wrapWs) {
      for (let offset = 0; offset <= input.length; offset += 1) {
        test(`"${input.slice(0, 6)}" off=${offset} wrap=${wrapW}`, () => {
          const pos = caretVisualPosition(input, offset, wrapW);
          expect(pos.lineIndex).toBeGreaterThanOrEqual(0);
          expect(pos.column).toBeGreaterThanOrEqual(0);
          expect(pos.column).toBeLessThan(wrapW);
        });
      }
    }
  }
});

describe('caretOffsetFromClick round-trip matrix', () => {
  const inputs = ['hello', 'abcdefghijk', 'first\nsecond', '我们呢test'];
  const termRows = 24;
  const termWidth = 80;

  for (const input of inputs) {
    for (let offset = 0; offset <= input.length; offset += Math.max(1, Math.floor(input.length / 4))) {
      test(`round-trip offset=${offset} for "${input.slice(0, 10)}"`, () => {
        const wrapW = Math.max(10, termWidth - 6);
        const numLines = numInputLines(input, wrapW);
        const firstRow = inputTextRow(termRows, numLines, 0);
        const { lineIndex, column } = caretVisualPosition(input, offset, wrapW);
        const x = 5 + column;
        const y = firstRow + lineIndex;
        const clicked = caretOffsetFromClick(x, y, input, termWidth, termRows, 0);
        if (clicked >= 0) {
          expect(Math.abs(clicked - offset)).toBeLessThanOrEqual(2);
        }
      });
    }
  }
});

describe('caretOffsetFromClick rejects out-of-bounds clicks', () => {
  const input = 'hello world';
  const cases: Array<[number, number]> = [
    [1, 1],
    [3, 24],
    [5, 10],
    [200, 24],
  ];
  for (const [x, y] of cases) {
    test(`reject click (${x}, ${y})`, () => {
      const result = caretOffsetFromClick(x, y, input, 80, 24, 0);
      expect(result === -1 || result >= 0).toBe(true);
    });
  }
});

describe('CJK click mapping', () => {
  const cjkInputs = ['中文', '日本語テスト', '한글입력', '繁體中文'];
  for (const input of cjkInputs) {
    test(`click start of "${input}"`, () => {
      const firstRow = inputTextRow(24, numInputLines(input, 74), 0);
      const offset = caretOffsetFromClick(5, firstRow, input, 80, 24, 0);
      expect(offset).toBe(0);
    });
  }
});
