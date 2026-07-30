/**
 * RxyCode OpenTUI entry (U1/U2 dual-entry shell).
 *
 * Terminal lifecycle: createCliRenderer({ useAlternateScreen: true }) enters
 * the alternate screen and owns stdin. On Ctrl+C / process exit, call
 * renderer.destroy() which leaves the alternate screen and restores the cursor.
 * Do NOT import Ink stdinBridge — OpenTUI owns stdin exclusively on this path.
 *
 * React peer: @opentui/react@0.4.5 requires react>=19.2.0 — isolated here so
 * the main Ink frontend/ package can stay on React 18.
 */
import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";
import App from "./App.tsx";
import { DialogProvider } from "./dialog/DialogHost.tsx";

if (!process.stdin.isTTY && process.env.RXYCODE_E2E_BYPASS_TTY !== "1") {
  console.log("RxyCode OpenTUI requires an interactive terminal (TTY).");
  console.log("Please run this directly in a terminal, not piped.");
  process.exit(1);
}

const renderer = await createCliRenderer({
  // Ctrl+C handled in App (copy selection / cancel stream / exit).
  exitOnCtrlC: false,
  useAlternateScreen: true,
  useMouse: true,
  enableMouseMovement: true,
});

const root = createRoot(renderer);

const cleanup = () => {
  try {
    root.unmount();
  } catch {
    // ignore
  }
  try {
    renderer.destroy();
  } catch {
    // destroy restores alternate screen / cursor when possible
  }
};

process.once("exit", cleanup);
process.once("SIGINT", () => {
  cleanup();
  process.exit(0);
});
process.once("SIGTERM", () => {
  cleanup();
  process.exit(0);
});

root.render(
  <DialogProvider>
    <App />
  </DialogProvider>,
);
