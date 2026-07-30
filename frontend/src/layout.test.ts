import { describe, test, expect } from 'vitest';
import { inputTextRow, numInputLines, caretOffsetFromClick, caretVisualPosition, cursorRowsFromFrameEnd } from './layout.js';

// Bug 1 + Bug 4 geometry: the input box is pinned above the 1-row StatusBar and
// its wrapped text lines stack UPWARD, so the first text row must move UP as the
// input grows. The cursor (Bug 1) and the click-to-cursor (Bug 4) both derive
// their position from these helpers, so they can never disagree.
describe('input box geometry (Bug 1 / Bug 4)', () => {
  test('first text row moves up as the input wraps to more lines', () => {
    // StatusBar=24, bottom border=23, single text line=22 (off-by-one 修复:
    // 旧公式返回 21，光标高出文字一行 = 问题2).
    expect(inputTextRow(24, 1, 0)).toBe(22);
    expect(inputTextRow(24, 2, 0)).toBe(21);
  });

  test('command list above the box does NOT move the bottom-pinned input', () => {
    // The `/` command list renders ABOVE the bordered box; the box stays
    // pinned to the bottom (frame overflow scrolls the TOP off-screen).
    expect(inputTextRow(24, 1, 12)).toBe(22);
  });

  test('cursorRowsFromFrameEnd is frame-relative (status bar + bottom border)', () => {
    // frame end line -> up1 = StatusBar, up2 = bottom border, up3 = text line.
    expect(cursorRowsFromFrameEnd(1, 0)).toBe(3);
    // 2 text lines: caret on line 0 (upper) = up4, line 1 (lower) = up3.
    expect(cursorRowsFromFrameEnd(2, 0)).toBe(4);
    expect(cursorRowsFromFrameEnd(2, 1)).toBe(3);
    // lineIndex clamped into [0, numTextLines-1].
    expect(cursorRowsFromFrameEnd(1, 5)).toBe(3);
  });

  test('numInputLines accounts for display width and CJK (width 2)', () => {
    expect(numInputLines('abc', 10)).toBe(1);
    expect(numInputLines('abcdefghijk', 10)).toBe(2); // 11 ascii = 2 lines @10
    expect(numInputLines('我们呢', 10)).toBe(1); // 3 cjk = width 6
    expect(numInputLines('我们呢我们呢我们呢', 10)).toBe(2); // width 12
  });

  test('explicit newlines create visual rows and move the caret', () => {
    const input = 'first\n第二行';
    expect(numInputLines(input, 20)).toBe(2);
    expect(caretVisualPosition(input, input.length, 20)).toEqual({ lineIndex: 1, column: 6 });
  });

  test('caretOffsetFromClick maps a click to the right character', () => {
    const input = 'hello';
    const termRows = 24, termWidth = 80, commandsAbove = 0;
    const firstRow = inputTextRow(termRows, 1, commandsAbove); // 21
    // x=5 is the first char cell (column 5), y on the text row -> offset 0
    expect(caretOffsetFromClick(5, firstRow, input, termWidth, termRows, commandsAbove)).toBe(0);
    expect(caretOffsetFromClick(6, firstRow, input, termWidth, termRows, commandsAbove)).toBe(1);
    expect(caretOffsetFromClick(9, firstRow, input, termWidth, termRows, commandsAbove)).toBe(4);
  });

  test('caretOffsetFromClick returns -1 for clicks outside the text block', () => {
    const input = 'hello';
    const termRows = 24, termWidth = 80, commandsAbove = 0;
    const firstRow = inputTextRow(termRows, 1, commandsAbove);
    expect(caretOffsetFromClick(5, firstRow - 1, input, termWidth, termRows, commandsAbove)).toBe(-1); // above
    expect(caretOffsetFromClick(5, firstRow + 1, input, termWidth, termRows, commandsAbove)).toBe(-1); // below (only 1 line)
    expect(caretOffsetFromClick(4, firstRow, input, termWidth, termRows, commandsAbove)).toBe(-1); // left of prompt
  });

  test('caretOffsetFromClick handles wrapped second line', () => {
    // termWidth 16 -> wrapW 10, so 11 ascii chars wrap onto a 2nd line.
    const input = 'abcdefghijk';
    const termRows = 24, termWidth = 16, commandsAbove = 0;
    const firstRow = inputTextRow(termRows, 2, commandsAbove); // 20
    // second visual line is y = firstRow + 1 = 21
    expect(caretOffsetFromClick(5, firstRow + 1, input, termWidth, termRows, commandsAbove)).toBe(10);
    expect(caretOffsetFromClick(6, firstRow + 1, input, termWidth, termRows, commandsAbove)).toBe(11);
  });

  test('caretOffsetFromClick maps clicks after an explicit newline', () => {
    const input = 'first\nsecond';
    const firstRow = inputTextRow(24, 2, 0);
    expect(caretOffsetFromClick(5, firstRow + 1, input, 80, 24, 0)).toBe(6);
    expect(caretOffsetFromClick(8, firstRow + 1, input, 80, 24, 0)).toBe(9);
  });

  test('caretOffsetFromClick never returns an offset inside a grapheme', () => {
    const input = 'A👨‍👩‍👧‍👦B';
    const firstRow = inputTextRow(24, 1, 0);
    expect([1, 12]).toContain(caretOffsetFromClick(7, firstRow, input, 80, 24, 0));
  });
});

