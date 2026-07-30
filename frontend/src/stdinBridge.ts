import { PassThrough } from 'node:stream';
import type { ReadStream, WriteStream } from 'node:tty';
import { parseSgr, MouseManager } from './mouse.js';

export interface MouseStdinHandle {
  /** Cleaned stream that Ink reads. Contains only real keypresses. */
  stdin: PassThrough;
  /** Detach the raw-stdin listener and reset terminal mouse mode. */
  stop(): void;
}

/**
 * Builds a "cleaned" stdin stream for Ink.
 *
 * `process.stdin` is read by a SINGLE owner here. Every chunk is scanned for
 * SGR 1006 mouse reports (`ESC [ < ... M|m`). Those are stripped out and
 * dispatched to the MouseManager as structured events; everything else (real
 * keypresses) is forwarded verbatim to the `cleaned` PassThrough that Ink
 * actually reads.
 *
 * Because Ink only ever sees the cleaned stream, mouse escape sequences can
 * never reach `ink-text-input` (which would otherwise append them as garbage
 * 乱码) nor trigger spurious re-renders (the 疯狂闪动 flicker).
 */
export function createMouseStdin(
  realStdin: ReadStream,
  realStdout: WriteStream,
  manager: MouseManager,
): MouseStdinHandle {
  // PassThrough that Ink reads. We delegate TTY capabilities to the real stdin
  // so Ink's useStdin/useInput (setRawMode) keep working.
  const cleaned = new PassThrough() as PassThrough & {
    isTTY: boolean;
    setRawMode: (mode: boolean) => void;
    ref: () => void;
    unref: () => void;
    columns: number;
    rows: number;
    isRawModeSupported: boolean;
  };
  cleaned.isTTY = true;
  cleaned.setRawMode = (mode: boolean) => {
    realStdin.setRawMode?.(mode as boolean);
  };
  // `PassThrough` does not implement `ref`/`unref` (those only exist on streams
  // backed by a real file descriptor). Ink's `handleSetRawMode` calls
  // `stdin.ref()` / `stdin.unref()` directly, so we delegate to the real TTY
  // stdin — otherwise the app crashes with `TypeError: stdin.ref is not a function`.
  cleaned.ref = () => {
    realStdin.ref?.();
  };
  cleaned.unref = () => {
    realStdin.unref?.();
  };
  cleaned.columns = realStdout.columns ?? 80;
  cleaned.rows = realStdout.rows ?? 40;
  cleaned.isRawModeSupported = true;

  const syncSize = () => {
    cleaned.columns = realStdout.columns ?? 80;
    cleaned.rows = realStdout.rows ?? 40;
    cleaned.emit('resize');
  };
  realStdout.on('resize', syncSize);
  try {
    realStdout.write('\x1b[?2004h');
  } catch {
    /* terminal may not support bracketed paste */
  }

  const ESC = 0x1b;
  const PASTE_START = Buffer.from('\x1b[200~', 'latin1');
  const PASTE_END = Buffer.from('\x1b[201~', 'latin1');
  let pending = Buffer.alloc(0);
  let pastePayload = Buffer.alloc(0);
  let inPaste = false;
  let escapeTimer: NodeJS.Timeout | null = null;

  const clearEscapeTimer = () => {
    if (escapeTimer) clearTimeout(escapeTimer);
    escapeTimer = null;
  };

  const flushLoneEscapeSoon = () => {
    clearEscapeTimer();
    escapeTimer = setTimeout(() => {
      if (pending.length === 1 && pending[0] === ESC) {
        cleaned.write(pending);
        pending = Buffer.alloc(0);
      }
      escapeTimer = null;
    }, 25);
    escapeTimer.unref?.();
  };

  const emitSequence = (sequence: Buffer) => {
    const encoded = sequence.toString('latin1');
    if (encoded === '\x1b[I' || encoded === '\x1b[O') return;
    const mouse = parseSgr(encoded);
    if (mouse) {
      manager.dispatch(mouse);
      return;
    }
    cleaned.write(sequence);
  };

  const drainPending = () => {
    clearEscapeTimer();
    while (pending.length > 0) {
      if (inPaste) {
        const combined = Buffer.concat([pastePayload, pending]);
        const end = combined.indexOf(PASTE_END);
        if (end === -1) {
          pastePayload = combined;
          pending = Buffer.alloc(0);
          return;
        }
        if (end > 0) cleaned.write(combined.subarray(0, end));
        pastePayload = Buffer.alloc(0);
        inPaste = false;
        pending = combined.subarray(end + PASTE_END.length);
        continue;
      }

      const escIndex = pending.indexOf(ESC);
      if (escIndex === -1) {
        cleaned.write(pending);
        pending = Buffer.alloc(0);
        return;
      }
      if (escIndex > 0) {
        cleaned.write(pending.subarray(0, escIndex));
        pending = pending.subarray(escIndex);
        continue;
      }
      if (pending.length === 1) {
        flushLoneEscapeSoon();
        return;
      }

      const introducer = pending[1];
      if (introducer === 0x5b) {
        let finalIndex = -1;
        for (let i = 2; i < pending.length; i += 1) {
          if (pending[i] >= 0x40 && pending[i] <= 0x7e) {
            finalIndex = i;
            break;
          }
        }
        if (finalIndex === -1) return;
        const sequence = pending.subarray(0, finalIndex + 1);
        pending = pending.subarray(finalIndex + 1);
        if (sequence.equals(PASTE_START)) {
          inPaste = true;
          pastePayload = Buffer.alloc(0);
          continue;
        }
        emitSequence(sequence);
        continue;
      }

      if (introducer === 0x4f) {
        if (pending.length < 3) return;
        emitSequence(pending.subarray(0, 3));
        pending = pending.subarray(3);
        continue;
      }

      emitSequence(pending.subarray(0, 2));
      pending = pending.subarray(2);
    }
  };

  const onData = (data: Buffer | string) => {
    const chunk = Buffer.isBuffer(data) ? data : Buffer.from(data);
    pending = Buffer.concat([pending, chunk]);
    drainPending();
  };

  realStdin.on('data', onData);

  let stopped = false;
  const stop = () => {
    if (stopped) return;
    stopped = true;
    realStdin.removeListener('data', onData);
    realStdout.removeListener('resize', syncSize);
    clearEscapeTimer();
    pending = Buffer.alloc(0);
    pastePayload = Buffer.alloc(0);
    inPaste = false;
    try {
      realStdout.write('\x1b[?2004l');
    } catch {
      /* ignore terminal teardown errors */
    }
  };

  return { stdin: cleaned, stop };
}
