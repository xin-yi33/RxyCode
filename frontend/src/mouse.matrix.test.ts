import { describe, it, expect } from 'vitest';
import { parseSgr } from './mouse.js';

const WHEEL_UP = '\x1b[<64;12;5M';
const WHEEL_DOWN = '\x1b[<65;12;5M';
const HOVER = '\x1b[<35;8;9M';
const CLICK = '\x1b[<0;8;9M';
const RELEASE = '\x1b[<0;8;9m';

describe('parseSgr button code matrix', () => {
  const cases: Array<[string, Partial<{ wheel: number; hover: boolean; click: boolean }>]> = [
    [WHEEL_UP, { wheel: -1, hover: false, click: false }],
    [WHEEL_DOWN, { wheel: 1, hover: false, click: false }],
    [HOVER, { wheel: 0, hover: true, click: false }],
    [CLICK, { wheel: 0, hover: false, click: true }],
    [RELEASE, { wheel: 0, hover: false, click: false }],
  ];

  for (const [seq, expected] of cases) {
    it(`parses ${JSON.stringify(seq.slice(-8))}`, () => {
      const e = parseSgr(seq);
      expect(e).not.toBeNull();
      expect(e).toMatchObject({ x: expect.any(Number), y: expect.any(Number), ...expected });
    });
  }
});

describe('parseSgr coordinate matrix', () => {
  for (let x = 1; x <= 20; x += 3) {
    for (let y = 1; y <= 10; y += 2) {
      it(`coords (${x}, ${y})`, () => {
        const seq = `\x1b[<0;${x};${y}M`;
        const e = parseSgr(seq);
        expect(e).toEqual({ x, y, wheel: 0, hover: false, click: true });
      });
    }
  }
});

describe('parseSgr rejects non-mouse sequences', () => {
  const invalid = [
    '\x1b[A',
    '\x1b[B',
    'hello',
    '',
    '\x1b[<invalid',
    '\x1b[<0;1;1X',
    '\x1b[?1006h',
    'plain text',
    '\x1b[<0;1;1',
  ];

  for (const seq of invalid) {
    it(`returns null for ${JSON.stringify(seq.slice(0, 10))}`, () => {
      expect(parseSgr(seq)).toBeNull();
    });
  }
});

describe('parseSgr motion variants', () => {
  const motionCodes = [32, 33, 34, 35, 36];
  for (const b of motionCodes) {
    it(`button code ${b} is hover/motion`, () => {
      const e = parseSgr(`\x1b[<${b};5;5M`);
      expect(e?.hover).toBe(true);
      expect(e?.click).toBe(false);
    });
  }
});

describe('parseSgr wheel variants', () => {
  for (const b of [64, 65, 66, 67]) {
    it(`wheel code ${b}`, () => {
      const e = parseSgr(`\x1b[<${b};1;1M`);
      expect(e?.wheel).toBe(b === 64 ? -1 : 1);
    });
  }
});

describe('parseSgr press vs release', () => {
  for (const b of [0, 1, 2]) {
    it(`button ${b} press`, () => {
      expect(parseSgr(`\x1b[<${b};3;3M`)?.click).toBe(b === 0);
    });
    it(`button ${b} release`, () => {
      expect(parseSgr(`\x1b[<${b};3;3m`)?.click).toBe(false);
    });
  }
});
