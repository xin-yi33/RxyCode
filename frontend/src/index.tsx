import React from 'react';
import { render } from 'ink';
import type { ReadStream } from 'node:tty';
import App from './App.js';
import { mouseManager } from './mouse.js';
import { createMouseStdin } from './stdinBridge.js';
import { initializeTerminalCursor } from './terminalCursor.js';
import { installTerminalLifecycle } from './terminalLifecycle.js';

// On some CI runners (e.g. GitHub Actions Windows), node-pty's ConPTY may not
// set process.stdin.isTTY to true even though a real pseudo-terminal exists.
// Allow an explicit bypass so the e2e harness can still drive the TUI.
if (!process.stdin.isTTY && process.env.RXYCODE_E2E_BYPASS_TTY !== '1') {
  console.log('RxyCode TUI requires an interactive terminal (TTY).');
  console.log('Please run this directly in a terminal, not piped.');
  process.exit(1);
}

// Attach the real stdout so the manager can toggle SGR mouse tracking, and
// create the single cleaned stdin reader that strips mouse reports before
// Ink sees them.
mouseManager.attach(process.stdout);
initializeTerminalCursor(process.stdout);
const bridge = createMouseStdin(process.stdin, process.stdout, mouseManager);

let cleanupTerminal = () => {};
const app = render(
  <App terminateProcess={() => {
    cleanupTerminal();
    setImmediate(() => process.exit(0));
  }} />,
  { stdin: bridge.stdin as unknown as ReadStream, stdout: process.stdout, exitOnCtrlC: false },
);
cleanupTerminal = installTerminalLifecycle({ app, bridge, mouseManager, stdout: process.stdout });
