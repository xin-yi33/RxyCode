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
// 废弃代码（2026-09-24）：appendFileSync 在本文件没有调用，只是残留导入。
// import { appendFileSync } from "node:fs";
import App from "./App.tsx";
import {
  consumeSgrMouseInput,
  resolveCliRendererMouseOptions,
  writeDisableAllMotion,
  writeDisableMouseTracking,
} from "./cliRendererOptions.ts";
import { DialogProvider } from "./dialog/DialogHost.tsx";
import { resolveTransportKind } from "./transport/config.ts";
import { getChatTransport } from "./transport/index.ts";
import { startStdioWarmOnOpen } from "./transport/stdioTransport.ts";

if (!process.stdin.isTTY && process.env.RXYCODE_E2E_BYPASS_TTY !== "1") {
  console.log("RxyCode OpenTUI requires an interactive terminal (TTY).");
  console.log("Please run this directly in a terminal, not piped.");
  process.exit(1);
}

// Foreign stderr (Node warnings, GUI apps that AttachConsole) paints over
// the alternate screen. Keep the TTY for OpenTUI stdout only.
{
  const origWrite = process.stderr.write.bind(process.stderr);
  process.stderr.write = ((
    chunk: string | Uint8Array,
    encoding?: BufferEncoding | ((err?: Error | null) => void),
    cb?: (err?: Error | null) => void,
  ) => {
    const text = typeof chunk === "string" ? chunk : Buffer.from(chunk).toString("utf8");
    if (process.env.RXYCODE_TUI_STDERR === "1") {
      return origWrite(chunk as never, encoding as never, cb as never);
    }
    if (typeof encoding === "function") encoding();
    else if (typeof cb === "function") cb();
    return true;
  }) as typeof process.stderr.write;
}

// Spawn / initialize appserver before the renderer so first paint overlaps warm.
if (resolveTransportKind() === "stdio") {
  startStdioWarmOnOpen();
}

const mouse = resolveCliRendererMouseOptions();
writeDisableAllMotion();

type CliRendererConfig = Parameters<typeof createCliRenderer>[0];

const renderer = await createCliRenderer({
  // Ctrl+C handled in App (copy selection / cancel stream / exit).
  exitOnCtrlC: false,
  useAlternateScreen: true,
  useMouse: mouse.useMouse,
  enableMouseMovement: mouse.enableMouseMovement,
  prependInputHandlers: [consumeSgrMouseInput],
} as CliRendererConfig);

const root = createRoot(renderer);

const cleanup = () => {
  writeDisableMouseTracking();
  try {
    void getChatTransport().shutdown?.();
  } catch {
    // ignore
  }
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
  writeDisableMouseTracking();
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
