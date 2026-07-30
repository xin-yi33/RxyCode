import type { MouseManager } from './mouse.js';
import type { MouseStdinHandle } from './stdinBridge.js';
import { restoreTerminalCursor, type TerminalWriter } from './terminalCursor.js';

interface InkAppHandle {
  unmount(): void;
  waitUntilExit(): Promise<void>;
}

interface ProcessHooks {
  once(event: string, listener: (...args: any[]) => void): unknown;
}

interface LifecycleOptions {
  app: InkAppHandle;
  bridge: Pick<MouseStdinHandle, 'stop'>;
  mouseManager: Pick<MouseManager, 'detach'>;
  stdout: TerminalWriter;
  processRef?: ProcessHooks;
}

export function installTerminalLifecycle({
  app,
  bridge,
  mouseManager,
  stdout,
  processRef = process,
}: LifecycleOptions): () => void {
  let cleaned = false;
  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    try { bridge.stop(); } catch { /* continue restoring terminal state */ }
    try { app.unmount(); } catch { /* continue restoring terminal state */ }
    try { mouseManager.detach(); } catch { /* continue restoring terminal state */ }
    restoreTerminalCursor(stdout);
  };

  processRef.once('SIGINT', cleanup);
  processRef.once('SIGTERM', cleanup);
  processRef.once('exit', cleanup);
  processRef.once('uncaughtExceptionMonitor', cleanup);
  void app.waitUntilExit().then(cleanup, cleanup);
  return cleanup;
}
