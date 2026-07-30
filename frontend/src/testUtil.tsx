import { render as inkRender } from 'ink';
import { EventEmitter } from 'node:events';
import React from 'react';

/**
 * Test render helper with a WIDE virtual terminal (1000 cols) so long lines
 * (e.g. the StatusBar, CJK titles) never wrap and trailing characters are not
 * dropped — ink-testing-library hardcodes columns=100 + debug mode, which
 * truncates/wraps wide mixed-width content and breaks substring assertions.
 */
class WideStdout extends EventEmitter {
  constructor(public columns = 1000, public rows = 100) {
    super();
  }
  frames: string[] = [];
  private _last?: string;
  write = (frame: string) => {
    this.frames.push(frame);
    this._last = frame;
  };
  lastFrame = () => this._last;
}

class WideStdin extends EventEmitter {
  isTTY = true;
  data: string | null = null;
  setRawMode = () => {};
  setEncoding = () => {};
  resume = () => {};
  pause = () => {};
  ref = () => {};
  unref = () => {};
  write = (data: string) => {
    this.data = data;
    this.emit('readable');
    this.emit('data', data);
  };
  read = () => {
    const { data } = this;
    this.data = null;
    return data;
  };
}

export function renderWide(tree: React.ReactElement) {
  return renderWithSize(tree, 1000, 100);
}

export function renderWithSize(tree: React.ReactElement, columns: number, rows: number) {
  const stdout = new WideStdout(columns, rows);
  const stdin = new WideStdin();
  const app = inkRender(tree, {
    stdout: stdout as any,
    stdin: stdin as any,
    exitOnCtrlC: false,
    patchConsole: false,
    debug: true,
  });
  return {
    lastFrame: () => stdout.lastFrame(),
    frames: () => stdout.frames,
    stdin,
    unmount: () => app.unmount(),
    waitUntilExit: () => app.waitUntilExit(),
  };
}
