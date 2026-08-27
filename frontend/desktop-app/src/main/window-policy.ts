/**
 * PhaseG-H3 window policy: Desktop is single-instance.
 * Closing one window must not imply a second Desktop sharing appserver;
 * a second process is refused and the existing window is focused.
 */
export const WINDOW_POLICY = 'single-instance' as const

export function shouldQuitSecondInstance(gotLock: boolean): boolean {
  return gotLock === false
}
