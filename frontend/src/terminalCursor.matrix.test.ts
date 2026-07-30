import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest';
import {
  hideTerminalCursor,
  initializeTerminalCursor,
  installCursorAnchor,
  positionTerminalCursor,
  restoreTerminalCursor,
  setCursorAnchor,
  uninstallCursorAnchor,
} from './terminalCursor.js';

function mockOut(isTTY: boolean) {
  return { isTTY, write: vi.fn() };
}

describe('positionTerminalCursor clamp matrix', () => {
  const cases: Array<[number, number, string]> = [
    [1, 1, '\x1b[?25h\x1b[1;1H'],
    [0, 0, '\x1b[?25h\x1b[1;1H'],
    [-5, -3, '\x1b[?25h\x1b[1;1H'],
    [7.8, 12.3, '\x1b[?25h\x1b[7;12H'],
    [24, 80, '\x1b[?25h\x1b[24;80H'],
    [100, 200, '\x1b[?25h\x1b[100;200H'],
  ];

  for (const [row, col, expected] of cases) {
    test(`row=${row} col=${col}`, () => {
      const out = mockOut(true);
      positionTerminalCursor(out, row, col);
      expect(out.write).toHaveBeenCalledWith(expected);
    });
  }
});

describe('non-TTY is silent matrix', () => {
  const fns = [
    (out: ReturnType<typeof mockOut>) => initializeTerminalCursor(out),
    (out: ReturnType<typeof mockOut>) => positionTerminalCursor(out, 5, 5),
    (out: ReturnType<typeof mockOut>) => hideTerminalCursor(out),
    (out: ReturnType<typeof mockOut>) => restoreTerminalCursor(out),
  ];

  for (let i = 0; i < fns.length; i += 1) {
    test(`function index ${i}`, () => {
      const out = mockOut(false);
      fns[i](out);
      expect(out.write).not.toHaveBeenCalled();
    });
  }
});

describe('cursor lifecycle sequences', () => {
  const sequences = [
    ['init', 'position', 'hide', 'restore'],
    ['init', 'hide', 'restore'],
    ['position', 'position', 'hide'],
  ] as const;

  for (const seq of sequences) {
    test(seq.join(' -> '), () => {
      const out = mockOut(true);
      for (const step of seq) {
        if (step === 'init') initializeTerminalCursor(out);
        if (step === 'position') positionTerminalCursor(out, 3, 10);
        if (step === 'hide') hideTerminalCursor(out);
        if (step === 'restore') restoreTerminalCursor(out);
      }
      expect(out.write.mock.calls.length).toBeGreaterThan(0);
    });
  }
});

describe('cursor anchor install/uninstall', () => {
  beforeEach(() => uninstallCursorAnchor());
  afterEach(() => uninstallCursorAnchor());

  test('wraps write and re-asserts anchor', () => {
    const writes: string[] = [];
    const out = {
      isTTY: true,
      write: vi.fn((chunk: string) => { writes.push(chunk); return true; }),
    };
    installCursorAnchor(out);
    setCursorAnchor(out, { rowsUp: 3, column: 10 });
    out.write('frame');
    expect(writes.length).toBeGreaterThan(1);
    uninstallCursorAnchor();
  });

  test('null anchor hides cursor', () => {
    const writes: string[] = [];
    const out = {
      isTTY: true,
      write: vi.fn((chunk: string) => { writes.push(chunk); return true; }),
    };
    installCursorAnchor(out);
    setCursorAnchor(out, { rowsUp: 2, column: 5 });
    setCursorAnchor(out, null);
    expect(writes.length).toBeGreaterThan(0);
  });

  test('non-TTY anchor is no-op', () => {
    const out = mockOut(false);
    installCursorAnchor(out);
    setCursorAnchor(out, { rowsUp: 1, column: 1 });
    expect(out.write).not.toHaveBeenCalled();
  });
});

describe('anchor rowsUp/column matrix', () => {
  beforeEach(() => uninstallCursorAnchor());
  afterEach(() => uninstallCursorAnchor());

  for (let rowsUp = 0; rowsUp <= 10; rowsUp += 1) {
    for (let column = 1; column <= 20; column += 5) {
      test(`rowsUp=${rowsUp} column=${column}`, () => {
        const writes: string[] = [];
        const out = {
          isTTY: true,
          write: vi.fn((chunk: string) => { writes.push(chunk); return true; }),
        };
        installCursorAnchor(out);
        setCursorAnchor(out, { rowsUp, column });
        out.write('x');
        expect(writes.some((c) => c.includes('\x1b['))).toBe(true);
        uninstallCursorAnchor();
      });
    }
  }
});

describe('initialize/restore blink sequences', () => {
  test('initialize enables blink and shows cursor', () => {
    const out = mockOut(true);
    initializeTerminalCursor(out);
    expect(out.write).toHaveBeenCalledWith('\x1b[?12h\x1b[?25h');
  });

  test('restore disables blink and shows cursor', () => {
    const out = mockOut(true);
    restoreTerminalCursor(out);
    expect(out.write).toHaveBeenCalledWith('\x1b[?12l\x1b[?25h');
  });
});

describe('hide cursor emits hide sequence', () => {
  for (let i = 0; i < 5; i += 1) {
    test(`call ${i}`, () => {
      const out = mockOut(true);
      hideTerminalCursor(out);
      expect(out.write).toHaveBeenCalledWith('\x1b[?25l');
    });
  }
});
