import { describe, it, expect, vi } from 'vitest';
import { parseSgr, MouseManager } from './mouse.js';

describe('parseSgr', () => {
  it('parses wheel up', () => {
    const e = parseSgr('\x1b[<64;12;5M');
    expect(e).toEqual({ x: 12, y: 5, wheel: -1, hover: false, click: false });
  });

  it('parses wheel down', () => {
    const e = parseSgr('\x1b[<65;12;5M');
    expect(e).toEqual({ x: 12, y: 5, wheel: 1, hover: false, click: false });
  });

  it('parses hover (motion, no button)', () => {
    const e = parseSgr('\x1b[<35;8;9M');
    expect(e).toEqual({ x: 8, y: 9, wheel: 0, hover: true, click: false });
  });

  it('parses left click (press)', () => {
    const e = parseSgr('\x1b[<0;8;9M');
    expect(e).toEqual({ x: 8, y: 9, wheel: 0, hover: false, click: true });
  });

  it('ignores release of left button', () => {
    const e = parseSgr('\x1b[<0;8;9m');
    expect(e).toEqual({ x: 8, y: 9, wheel: 0, hover: false, click: false });
  });

  it('returns null for non-mouse sequences', () => {
    expect(parseSgr('\x1b[A')).toBeNull();
    expect(parseSgr('hello')).toBeNull();
  });
});

describe('MouseManager', () => {
  it('keeps terminal mouse tracking disabled by default for native selection', () => {
    const writes: string[] = [];
    const fakeStdout = { write: (s: string) => { writes.push(s); return true; } } as any;
    const m = new MouseManager();
    m.attach(fakeStdout);

    const off = m.subscribe(vi.fn());
    off();

    expect(writes).toEqual([]);
  });

  it('dispatches parsed events to subscribers', () => {
    const m = new MouseManager();
    const cb = vi.fn();
    m.subscribe(cb);
    m.dispatch({ x: 10, y: 5, wheel: -1, hover: false, click: false });
    m.dispatch({ x: 10, y: 6, wheel: 0, hover: true, click: false });
    expect(cb).toHaveBeenCalledTimes(2);
    expect(cb.mock.calls[0][0].wheel).toBe(-1);
    expect(cb.mock.calls[1][0].hover).toBe(true);
  });

  it('unsubscribe stops delivery', () => {
    const m = new MouseManager();
    const cb = vi.fn();
    const off = m.subscribe(cb);
    off();
    m.dispatch({ x: 1, y: 1, wheel: 0, hover: true, click: false });
    expect(cb).not.toHaveBeenCalled();
  });

  it('enables tracking on first subscribe, disables on last unsubscribe when opted in', () => {
    const writes: string[] = [];
    const fakeStdout = { write: (s: string) => { writes.push(s); return true; } } as any;
    const m = new MouseManager(true);
    m.attach(fakeStdout);

    const off1 = m.subscribe(vi.fn());
    const off2 = m.subscribe(vi.fn());
    expect(writes).toContain('\x1b[?1006h');
    expect(writes).toContain('\x1b[?1002h');

    off1();
    // still one subscriber -> tracking stays on
    expect(writes.filter((w) => w === '\x1b[?1002l')).toHaveLength(0);

    off2();
    expect(writes).toContain('\x1b[?1002l');
    expect(writes).toContain('\x1b[?1006l');
  });

  it('detach restores opted-in mouse modes even with mounted subscribers', () => {
    const writes: string[] = [];
    const m = new MouseManager(true);
    m.attach({ write: (chunk: string) => { writes.push(chunk); return true; } } as any);
    m.subscribe(vi.fn());

    m.detach();

    expect(writes.slice(-2)).toEqual(['\x1b[?1002l', '\x1b[?1006l']);
  });
});
