/**
 * OpenTUI mouse tracking.
 *
 * Scroll, copy, and hover highlight need useMouse. All-motion 1003 emits
 * ESC [ < 35 ; x ; y M; consumeSgrMouseInput eats those so they never
 * leak into the composer. Hover is on by default; RXYCODE_MOUSE_MOVE=0
 * turns it off. RXYCODE_MOUSE=0 disables tracking.
 */
export type CliRendererMouseOptions = {
  useMouse: boolean;
  enableMouseMovement: boolean;
};

export const DISABLE_ALL_MOTION = "\x1b[?1003l";
export const DISABLE_MOUSE_TRACKING = "\x1b[?1003l\x1b[?1002l\x1b[?1000l\x1b[?1006l";

/** Hover-only SGR (button 35). Must not match click / drag / wheel. */
const SGR_HOVER = /(?:\x1b)?\[<35;\d+;\d+[Mm]/;

export function isWindowsHost(platform: NodeJS.Platform = process.platform): boolean {
  return platform === "win32";
}

export function resolveCliRendererMouseOptions(
  env: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): CliRendererMouseOptions {
  const forceOff = env.RXYCODE_MOUSE === "0";
  const forceMoveOff = env.RXYCODE_MOUSE_MOVE === "0";
  if (forceOff) {
    return { useMouse: false, enableMouseMovement: false };
  }
  return {
    useMouse: true,
    // Hover highlight (plan buttons) needs movement. Hover SGR is eaten by
    // consumeSgrMouseInput so it does not leak into the composer.
    enableMouseMovement: !forceMoveOff,
  };
}

export function writeDisableAllMotion(
  stream: { write: (chunk: string) => unknown } = process.stdout,
): void {
  try {
    stream.write(DISABLE_ALL_MOTION);
  } catch {
    // terminal may already be gone
  }
}

export function writeDisableMouseTracking(
  stream: { write: (chunk: string) => unknown } = process.stdout,
): void {
  try {
    stream.write(DISABLE_MOUSE_TRACKING);
  } catch {
    // terminal may already be gone
  }
}

/** Eat leftover hover reports so they never reach the textarea as text. */
export function consumeSgrMouseInput(sequence: string): boolean {
  return SGR_HOVER.test(sequence);
}
