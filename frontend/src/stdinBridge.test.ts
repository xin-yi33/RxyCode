import { describe, it, expect, vi } from 'vitest';
import { EventEmitter } from 'node:events';
import { createMouseStdin } from './stdinBridge.js';
import { MouseManager } from './mouse.js';

function makeFakeStdin() {
  const e = new EventEmitter() as any;
  e.isTTY = true;
  e.setRawMode = () => {};
  e.columns = 80;
  e.rows = 40;
  return e;
}

function makeFakeStdout() {
  const e = new EventEmitter() as any;
  e.columns = 80;
  e.rows = 40;
  e.write = () => true;
  return e;
}

describe('stdinBridge (single reader, mouse stripping)', () => {
  it('strips SGR mouse reports and forwards only real keypresses', () => {
    const stdin = makeFakeStdin();
    const stdout = makeFakeStdout();
    const mgr = new MouseManager();
    const onMouse = vi.fn();
    mgr.subscribe(onMouse);
    const { stdin: cleaned } = createMouseStdin(stdin, stdout, mgr);

    const captured: string[] = [];
    cleaned.on('data', (b: Buffer) => captured.push(b.toString('latin1')));

    // A real keypress (down arrow) interleaved with a hover report.
    const chunk = Buffer.from('\x1b[<35;10;20M' + '\x1b[B', 'latin1');
    stdin.emit('data', chunk);

    expect(onMouse).toHaveBeenCalledTimes(1);
    expect(onMouse.mock.calls[0][0].hover).toBe(true);

    const out = captured.join('');
    // The critical assertion: mouse escape sequences never reach Ink/text input.
    expect(out).not.toContain('\x1b[<');
    // But real keypresses are preserved.
    expect(out).toContain('\x1b[B');
  });

  it('does not leak wheel/click garbage either', () => {
    const stdin = makeFakeStdin();
    const stdout = makeFakeStdout();
    const mgr = new MouseManager();
    const onMouse = vi.fn();
    mgr.subscribe(onMouse);
    const { stdin: cleaned } = createMouseStdin(stdin, stdout, mgr);

    const captured: string[] = [];
    cleaned.on('data', (b: Buffer) => captured.push(b.toString('latin1')));

    stdin.emit('data', Buffer.from('\x1b[<64;10;5M\x1b[<0;8;9M', 'latin1')); // wheel up + click
    expect(onMouse).toHaveBeenCalledTimes(2);
    expect(captured.join('')).not.toContain('\x1b[<');
  });

  it('reassembles a mouse report split across two chunks', () => {
    const stdin = makeFakeStdin();
    const stdout = makeFakeStdout();
    const mgr = new MouseManager();
    const onMouse = vi.fn();
    mgr.subscribe(onMouse);
    const { stdin: cleaned } = createMouseStdin(stdin, stdout, mgr);

    const captured: string[] = [];
    cleaned.on('data', (b: Buffer) => captured.push(b.toString('latin1')));

    stdin.emit('data', Buffer.from('\x1b[<64;10;', 'latin1'));
    expect(onMouse).not.toHaveBeenCalled(); // partial, held back
    stdin.emit('data', Buffer.from('5M', 'latin1'));
    expect(onMouse).toHaveBeenCalledTimes(1);
    expect(onMouse.mock.calls[0][0].wheel).toBe(-1);
    expect(captured.join('')).not.toContain('\x1b[<');
  });

  it('forwards multi-byte UTF-8 keypresses without corruption', () => {
    const stdin = makeFakeStdin();
    const stdout = makeFakeStdout();
    const mgr = new MouseManager();
    mgr.subscribe(vi.fn());
    const { stdin: cleaned } = createMouseStdin(stdin, stdout, mgr);

    const captured: Buffer[] = [];
    cleaned.on('data', (b: Buffer) => captured.push(b));

    const input = Buffer.from('你好', 'utf8');
    stdin.emit('data', input.subarray(0, 2));
    stdin.emit('data', input.subarray(2));
    expect(Buffer.concat(captured).toString('utf8')).toBe('你好');
  });

  it('reassembles split CSI and SS3 key sequences as individual input events', () => {
    const stdin = makeFakeStdin();
    const stdout = makeFakeStdout();
    const mgr = new MouseManager();
    const { stdin: cleaned } = createMouseStdin(stdin, stdout, mgr);
    const captured: string[] = [];
    cleaned.on('data', (b: Buffer) => captured.push(b.toString('latin1')));

    stdin.emit('data', Buffer.from('\x1b[', 'latin1'));
    expect(captured).toEqual([]);
    stdin.emit('data', Buffer.from('A\x1bO', 'latin1'));
    expect(captured).toEqual(['\x1b[A']);
    stdin.emit('data', Buffer.from('P', 'latin1'));
    expect(captured).toEqual(['\x1b[A', '\x1bOP']);
  });

  it('consumes terminal focus reports instead of forwarding them as text', () => {
    const stdin = makeFakeStdin();
    const stdout = makeFakeStdout();
    const mgr = new MouseManager();
    const { stdin: cleaned } = createMouseStdin(stdin, stdout, mgr);
    const captured: Buffer[] = [];
    cleaned.on('data', (b: Buffer) => captured.push(b));

    stdin.emit('data', Buffer.from('\x1b[Ihello\x1b[O', 'latin1'));
    expect(Buffer.concat(captured).toString('utf8')).toBe('hello');
  });

  it('strips bracketed-paste wrappers and preserves a payload split across chunks', () => {
    const stdin = makeFakeStdin();
    const stdout = makeFakeStdout();
    const mgr = new MouseManager();
    const { stdin: cleaned } = createMouseStdin(stdin, stdout, mgr);
    const captured: Buffer[] = [];
    cleaned.on('data', (b: Buffer) => captured.push(b));

    stdin.emit('data', Buffer.from('\x1b[20', 'latin1'));
    stdin.emit('data', Buffer.from('0~你好\nwor', 'utf8'));
    stdin.emit('data', Buffer.from('ld\x1b[201', 'utf8'));
    stdin.emit('data', Buffer.from('~', 'latin1'));

    expect(Buffer.concat(captured).toString('utf8')).toBe('你好\nworld');
  });

  it('frames multiple key sequences from one raw chunk separately', () => {
    const stdin = makeFakeStdin();
    const stdout = makeFakeStdout();
    const mgr = new MouseManager();
    const { stdin: cleaned } = createMouseStdin(stdin, stdout, mgr);
    const captured: string[] = [];
    cleaned.on('data', (b: Buffer) => captured.push(b.toString('latin1')));

    stdin.emit('data', Buffer.from('\x1b[A\x1b[Bx', 'latin1'));
    expect(captured).toEqual(['\x1b[A', '\x1b[B', 'x']);
  });

  it('forwards a standalone Escape key after the sequence window', () => {
    vi.useFakeTimers();
    const stdin = makeFakeStdin();
    const stdout = makeFakeStdout();
    const mgr = new MouseManager();
    const { stdin: cleaned, stop } = createMouseStdin(stdin, stdout, mgr);
    const captured: string[] = [];
    cleaned.on('data', (b: Buffer) => captured.push(b.toString('latin1')));

    stdin.emit('data', Buffer.from('\x1b', 'latin1'));
    expect(captured).toEqual([]);
    vi.advanceTimersByTime(25);
    expect(captured).toEqual(['\x1b']);

    stop();
    vi.useRealTimers();
  });

  it('stop() detaches the raw listener and is idempotent', () => {
    const stdin = makeFakeStdin();
    const stdout = makeFakeStdout();
    const mgr = new MouseManager();
    mgr.subscribe(vi.fn());
    const handle = createMouseStdin(stdin, stdout, mgr);
    const before = (stdin as any).listenerCount('data');
    expect(before).toBeGreaterThan(0);
    handle.stop();
    handle.stop();
    expect((stdin as any).listenerCount('data')).toBe(0);
  });

  it('cleaned stdin exposes the TTY methods Ink handleSetRawMode requires (regression for crash)', () => {
    // Ink's <App> calls stdin.ref() / stdin.unref() / stdin.setRawMode() during
    // useInput's effect. A PassThrough does NOT implement ref/unref, so without
    // these delegations `node dist/index.js` crashes with
    // "TypeError: stdin.ref is not a function" at App.js:118.
    const stdin = makeFakeStdin();
    const stdout = makeFakeStdout();
    const mgr = new MouseManager();
    mgr.subscribe(vi.fn());
    const { stdin: cleaned } = createMouseStdin(stdin, stdout, mgr);

    expect(cleaned.isTTY).toBe(true);
    expect(typeof (cleaned as any).setRawMode).toBe('function');
    expect(typeof (cleaned as any).ref).toBe('function');
    expect(typeof (cleaned as any).unref).toBe('function');

    const refSpy = vi.fn();
    const unrefSpy = vi.fn();
    const rawSpy = vi.fn();
    (stdin as any).ref = refSpy;
    (stdin as any).unref = unrefSpy;
    (stdin as any).setRawMode = rawSpy;

    (cleaned as any).ref();
    (cleaned as any).unref();
    (cleaned as any).setRawMode(true);
    (cleaned as any).setRawMode(false);

    expect(refSpy).toHaveBeenCalledTimes(1);
    expect(unrefSpy).toHaveBeenCalledTimes(1);
    expect(rawSpy).toHaveBeenCalledTimes(2);
    expect(rawSpy).toHaveBeenNthCalledWith(1, true);
    expect(rawSpy).toHaveBeenNthCalledWith(2, false);
  });

  it('enables bracketed paste while active and disables it on stop', () => {
    const stdin = makeFakeStdin();
    const stdout = makeFakeStdout();
    const writes: string[] = [];
    stdout.write = (chunk: string) => { writes.push(chunk); return true; };
    const handle = createMouseStdin(stdin, stdout, new MouseManager());

    expect(writes).toContain('\x1b[?2004h');
    handle.stop();
    handle.stop();
    expect(writes.filter((chunk) => chunk === '\x1b[?2004l')).toHaveLength(1);
  });
});
