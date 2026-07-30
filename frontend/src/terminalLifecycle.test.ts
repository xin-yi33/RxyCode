import { EventEmitter } from 'node:events';
import { describe, expect, test, vi } from 'vitest';
import { installTerminalLifecycle } from './terminalLifecycle.js';

describe('terminal lifecycle', () => {
  test('normal Ink exit restores bridge, mouse modes and cursor exactly once', async () => {
    let resolveExit!: () => void;
    const waitUntilExit = new Promise<void>((resolve) => { resolveExit = resolve; });
    const writes: string[] = [];
    const processRef = new EventEmitter() as NodeJS.Process;
    const bridge = { stop: vi.fn() };
    const app = { unmount: vi.fn(), waitUntilExit: () => waitUntilExit };
    const mouse = { detach: vi.fn() };

    installTerminalLifecycle({
      app,
      bridge,
      mouseManager: mouse,
      stdout: { isTTY: true, write: (chunk: string) => { writes.push(chunk); } },
      processRef,
    });
    resolveExit();
    await waitUntilExit;
    await Promise.resolve();

    expect(bridge.stop).toHaveBeenCalledTimes(1);
    expect(app.unmount).toHaveBeenCalledTimes(1);
    expect(mouse.detach).toHaveBeenCalledTimes(1);
    expect(writes).toEqual(['\x1b[?12l\x1b[?25h']);
  });

  test('signal and process-exit cleanup are idempotent', () => {
    const processRef = new EventEmitter() as NodeJS.Process;
    const bridge = { stop: vi.fn() };
    const app = { unmount: vi.fn(), waitUntilExit: () => new Promise<void>(() => {}) };
    const mouse = { detach: vi.fn() };
    const write = vi.fn();

    installTerminalLifecycle({
      app,
      bridge,
      mouseManager: mouse,
      stdout: { isTTY: true, write },
      processRef,
    });
    processRef.emit('SIGTERM');
    processRef.emit('exit', 0);

    expect(bridge.stop).toHaveBeenCalledTimes(1);
    expect(app.unmount).toHaveBeenCalledTimes(1);
    expect(mouse.detach).toHaveBeenCalledTimes(1);
    expect(write).toHaveBeenCalledTimes(1);
  });
});
