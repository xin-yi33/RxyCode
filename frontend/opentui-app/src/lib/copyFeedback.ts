/**
 * One copy-feedback window for the whole TUI.
 *
 * The "Copied to clipboard" chip is a transient acknowledgement: it appears
 * only after the OSC52 write actually returns, stays for exactly
 * COPY_FEEDBACK_MS, then reverts.  A failed copy shows a failure chip — never
 * a success chip (no fake success).
 */
import { useCallback, useEffect, useRef, useState } from "react";

/** Shared copy→revert window. Do not scatter 2500/3000ms literals. */
export const COPY_FEEDBACK_MS = 2500;

export interface CopyFeedback {
  ok: boolean;
  label: string;
}

export function copyFeedbackLabel(ok: boolean): string {
  return ok ? " Copied to clipboard " : " 复制失败：终端不支持 OSC52 剪贴板 ";
}

export interface CopyFeedbackController {
  feedback: CopyFeedback | null;
  /** Show the acknowledgement for the shared window, restarting any pending timer. */
  flash: (ok: boolean) => void;
  clear: () => void;
}

/** React hook used by App; delayMs is injectable so tests need not wait 2.5s. */
export function useCopyFeedback(delayMs: number = COPY_FEEDBACK_MS): CopyFeedbackController {
  const [feedback, setFeedback] = useState<CopyFeedback | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clear = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setFeedback(null);
  }, []);

  const flash = useCallback(
    (ok: boolean) => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      setFeedback({ ok, label: copyFeedbackLabel(ok) });
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        setFeedback(null);
      }, Math.max(0, Math.trunc(delayMs)));
    },
    [delayMs],
  );

  useEffect(
    () => () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    },
    [],
  );

  return { feedback, flash, clear };
}
