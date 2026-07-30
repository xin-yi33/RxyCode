import { createContext, useContext, useEffect, useRef } from 'react';
import type { WriteStream } from 'node:tty';

export interface MouseEventData {
  /** 1-based column (SGR 1006) */
  x: number;
  /** 1-based row (SGR 1006) */
  y: number;
  /** -1 = wheel up, +1 = wheel down, 0 = none */
  wheel: number;
  /** cursor moved over a cell (hover) */
  hover: boolean;
  /** left button pressed on a cell (click) */
  click: boolean;
}

export type MouseSubscriber = (e: MouseEventData) => void;

/**
 * Parse a single SGR 1006 mouse report:  ESC [ < B ; X ; Y (M|m)
 *  - B >= 64            -> wheel (64 = up, 65 = down)
 *  - (B & 32) && B < 64 -> motion / hover (35 = hover no button)
 *  - B === 0 && press   -> left click
 */
export function parseSgr(seq: string): MouseEventData | null {
  const m = /^\x1b\[<(\d+);(\d+);(\d+)([Mm])$/.exec(seq);
  if (!m) return null;
  const b = parseInt(m[1], 10);
  const x = parseInt(m[2], 10);
  const y = parseInt(m[3], 10);
  const release = m[4] === 'm';
  let wheel = 0;
  let hover = false;
  let click = false;
  if (b >= 64) {
    wheel = b === 64 ? -1 : 1;
  } else if ((b & 32) !== 0 && b < 64) {
    hover = true;
  } else if (b === 0 && !release) {
    click = true;
  }
  return { x, y, wheel, hover, click };
}

/**
 * Pure mouse-event dispatcher.
 *
 * This class intentionally does NOT own a raw-stdin listener. The raw stdin is
 * owned exclusively by the stdin bridge (see stdinBridge.ts), which strips SGR
 * mouse reports out of the byte stream BEFORE Ink sees them and dispatches the
 * parsed events here. That single-reader design is what prevents:
 *   (a) mouse escape sequences leaking into text inputs as garbage (乱码), and
 *   (b) per-pixel re-render flicker (疯狂闪动).
 *
 * Terminal mouse tracking is disabled by default so native selection, copy,
 * and scrollback keep working. Set RXYCODE_MOUSE=1 to opt in; tracking then
 * remains active only while at least one subscriber is mounted.
 */
export class MouseManager {
  private stdout: WriteStream | null = null;
  private subscribers = new Set<MouseSubscriber>();
  private tracking = false;

  constructor(private readonly trackingEnabled = false) {}

  attach(stdout: WriteStream) {
    this.stdout = stdout;
  }

  detach() {
    this.disableTracking();
    this.stdout = null;
  }

  private enableTracking() {
    if (this.tracking) return;
    this.tracking = true;
    try {
      this.stdout?.write('\x1b[?1006h');
      this.stdout?.write('\x1b[?1002h');
    } catch {
      /* terminal may not support it; ignore */
    }
  }

  private disableTracking() {
    if (!this.tracking) return;
    this.tracking = false;
    try {
      this.stdout?.write('\x1b[?1002l');
      this.stdout?.write('\x1b[?1006l');
    } catch {
      /* ignore */
    }
  }

  subscribe(cb: MouseSubscriber): () => void {
    const wasEmpty = this.subscribers.size === 0;
    this.subscribers.add(cb);
    if (wasEmpty && this.trackingEnabled) this.enableTracking();
    return () => {
      this.subscribers.delete(cb);
      if (this.subscribers.size === 0) this.disableTracking();
    };
  }

  /** @internal called by the stdin bridge */
  dispatch(e: MouseEventData) {
    this.subscribers.forEach((cb) => cb(e));
  }
}

export const mouseManager = new MouseManager(process.env.RXYCODE_MOUSE === '1');

const MouseContext = createContext<MouseManager>(mouseManager);
export const MouseProvider = MouseContext.Provider;
export const useMouseManager = () => useContext(MouseContext);

/**
 * Wire a bottom-anchored list to the global mouse manager.
 *
 * Geometry assumptions (verified against the App layout):
 *   - ChatPanel uses flexGrow and eats all vertical space, so the list is
 *     flush against the bottom, directly above the 1-row StatusBar.
 *   - listHeight = total rendered rows of the list box.
 *   - offset     = rows from the list's top border to its first item row.
 *
 * Selection is updated ONLY when the hovered/clicked index actually changes,
 * which is what prevents the per-pixel re-render flicker.
 */
export function useListMouse(
  enabled: boolean,
  opts: {
    rows: number;
    listHeight: number;
    offset: number;
    slotCount: number;
    resolveSlot: (slot: number) => number | null;
    onHover?: (globalIndex: number) => void;
    onClick: (globalIndex: number) => void;
    onWheel: (delta: number) => void;
  },
) {
  const mgr = useMouseManager();
  const optsRef = useRef(opts);
  optsRef.current = opts;
  const lastHover = useRef(-1);
  const lastHoverT = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    const unsub = mgr.subscribe((e) => {
      const p = optsRef.current;
      // ChatPanel flexGrows and eats all height, so the list is flush at the
      // bottom, directly above the 1-row StatusBar. listHeight already includes
      // both borders, so the list's top row = rows - listHeight.
      const topRow = p.rows - p.listHeight;
      const firstItemRow = topRow + p.offset;

      if (e.wheel !== 0) {
        p.onWheel(e.wheel);
        return;
      }
      if (!e.hover && !e.click) return;

      const slot = e.y - firstItemRow;
      if (slot < 0 || slot >= p.slotCount) return;
      const gi = p.resolveSlot(slot);
      if (gi === null || gi === undefined) return;

      if (e.hover) {
        const now = Date.now();
        if (now - lastHoverT.current < 16) return; // throttle hover spam
        lastHoverT.current = now;
        if (gi === lastHover.current) return; // no change -> no re-render
        lastHover.current = gi;
        p.onHover?.(gi);
      } else if (e.click) {
        p.onClick(gi);
      }
    });
    return unsub;
  }, [mgr, enabled]);
}
