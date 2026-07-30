import { describe, expect, test, vi } from 'vitest';
import {
  hideTerminalCursor,
  initializeTerminalCursor,
  positionTerminalCursor,
  restoreTerminalCursor,
} from './terminalCursor.js';

describe('terminal cursor lifecycle', () => {
  test('initializes, positions, hides and restores a TTY cursor', () => {
    const write = vi.fn();
    const out = { isTTY: true, write };

    initializeTerminalCursor(out);
    positionTerminalCursor(out, 0, 7.8);
    hideTerminalCursor(out);
    restoreTerminalCursor(out);

    expect(write.mock.calls.map(([chunk]) => chunk)).toEqual([
      '\x1b[?12h\x1b[?25h',
      '\x1b[?25h\x1b[1;7H',
      '\x1b[?25l',
      '\x1b[?12l\x1b[?25h',
    ]);
  });

  test('does not emit control sequences for non-TTY output', () => {
    const write = vi.fn();
    const out = { isTTY: false, write };
    initializeTerminalCursor(out);
    positionTerminalCursor(out, 1, 1);
    hideTerminalCursor(out);
    restoreTerminalCursor(out);
    expect(write).not.toHaveBeenCalled();
  });
});
