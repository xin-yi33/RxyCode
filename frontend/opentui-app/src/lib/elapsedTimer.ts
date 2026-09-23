/** Reusable elapsed-time formatter for Thought, tools, and later status lines. */

export class ElapsedTimer {
  readonly startedAtMs: number;

  constructor(startedAtMs: number = Date.now()) {
    this.startedAtMs = startedAtMs;
  }

  static start(now: number = Date.now()): ElapsedTimer {
    return new ElapsedTimer(now);
  }

  elapsedMs(now: number = Date.now()): number {
    return Math.max(0, now - this.startedAtMs);
  }

  format(now: number = Date.now()): string {
    return formatElapsed(this.elapsedMs(now));
  }
}

export function formatElapsed(elapsedMs: number): string {
  const ms = Math.max(0, Math.round(elapsedMs));
  if (ms < 1000) return `${ms}ms`;
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const totalSec = Math.floor(sec);
  if (totalSec < 3600) {
    const minutes = Math.floor(totalSec / 60);
    const seconds = totalSec % 60;
    return `${minutes} min ${seconds} s`;
  }
  const hours = Math.floor(totalSec / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  return `${hours} h ${minutes} min`;
}
