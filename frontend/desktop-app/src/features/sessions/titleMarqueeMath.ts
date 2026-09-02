/** Constant-velocity marquee. Same formula as OpenCode #13210 / Cherry Studio #13168. */
export const MARQUEE_PX_PER_SEC = 32
export const MARQUEE_MIN_DURATION_SEC = 8

export function marqueeOverflowPx(scrollWidth: number, clientWidth: number): number {
  return Math.max(0, Math.ceil(scrollWidth - clientWidth))
}

export function marqueeDurationSec(overflowPx: number, pxPerSec = MARQUEE_PX_PER_SEC): number {
  if (overflowPx <= 0) return 0
  const speed = pxPerSec > 0 ? pxPerSec : MARQUEE_PX_PER_SEC
  return overflowPx / speed
}

export function sharedMarqueePxPerSec(
  overflows: readonly number[],
  _minDurationSec = MARQUEE_MIN_DURATION_SEC
): number {
  const longest = overflows.reduce((max, value) => (value > max ? value : max), 0)
  if (longest <= 0) return MARQUEE_PX_PER_SEC
  return MARQUEE_PX_PER_SEC
}
