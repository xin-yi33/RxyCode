import { stripAnsiSequences } from "@opentui/core";
import { dirname, resolve } from "node:path";
import { stat as statFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import {
  MAX_CLIPBOARD_ATTACHMENTS,
  MAX_CLIPBOARD_PATH_LENGTH,
  validateClipboardAttachments,
  type ClipboardAttachment,
} from "./clipboardAttachments.ts";

export type { ClipboardAttachment };
export {
  MAX_CLIPBOARD_ATTACHMENTS,
  MAX_CLIPBOARD_PATH_LENGTH,
  validateClipboardAttachments,
};

export type ClipboardCaptureResult = {
  kind: "text" | "attachments" | "empty" | "error";
  text: string;
  attachments: ClipboardAttachment[];
  error?: string;
};

const HELPER_TIMEOUT_MS = 3_500;
const MAX_HELPER_OUTPUT_BYTES = 256 * 1024;
const SOURCE_PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");

type ClipboardHelperChild = {
  pid: number;
  stdout: ReadableStream<Uint8Array>;
  exited: Promise<number>;
  kill(): void;
};

let captureOverrideForTests: ((signal?: AbortSignal) => Promise<ClipboardCaptureResult>) | null = null;
let clipboardSpawnOverrideForTests: ((command: string[]) => ClipboardHelperChild) | null = null;

/** Test seam for App/native-key tests; production always launches the Python helper. */
export function __setClipboardCaptureForTests(
  capture: ((signal?: AbortSignal) => Promise<ClipboardCaptureResult>) | null,
): void {
  captureOverrideForTests = capture;
}

/** Test seam for exercising child exit/stdout handling without launching Python. */
export function __setClipboardSpawnForTests(
  spawn: ((command: string[]) => ClipboardHelperChild) | null,
): void {
  clipboardSpawnOverrideForTests = spawn;
}

export function getAttachmentName(attachment: ClipboardAttachment): string {
  const candidate = attachment.name?.trim() || attachment.path;
  const parts = candidate.split(/[\\/]/).filter(Boolean);
  const basename = parts.at(-1) || candidate || "attachment";
  return stripAnsiSequences(basename)
    .replace(/[\u0000-\u001F\u007F-\u009F\u2028\u2029]/g, " ")
    .replace(/\s+/g, " ")
    .trim() || "attachment";
}

export function getAttachmentKind(attachment: ClipboardAttachment): string {
  const name = getAttachmentName(attachment).toLowerCase();
  const ext = name.includes(".") ? name.slice(name.lastIndexOf(".") + 1) : "";
  if (["png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff", "ico"].includes(ext)) return "image";
  if (ext === "pdf") return "pdf";
  if (["txt", "md", "json", "csv", "ts", "tsx", "js", "jsx", "py", "toml", "yaml", "yml", "xml", "html", "css"].includes(ext)) return "text";
  return "file";
}

function isLocalAbsoluteWindowsPath(value: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(value);
}

function parsePathLine(line: string): string[] | null {
  const paths: string[] = [];
  let rest = line.trim();
  while (rest) {
    rest = rest.trimStart();
    if (!rest) break;

    let item: string;
    if (rest.startsWith('"') || rest.startsWith("'")) {
      const quote = rest[0]!;
      const end = rest.indexOf(quote, 1);
      if (end < 0) return null;
      item = rest.slice(1, end);
      rest = rest.slice(end + 1).trimStart();
    } else {
      const nextPath = rest.search(/\s+(?=[A-Za-z]:[\\/])/);
      if (nextPath >= 0) {
        item = rest.slice(0, nextPath).trim();
        rest = rest.slice(nextPath).trimStart();
      } else {
        item = rest;
        rest = "";
      }
    }
    if (!isLocalAbsoluteWindowsPath(item) || item.length > MAX_CLIPBOARD_PATH_LENGTH) return null;
    paths.push(item);
    if (paths.length > MAX_CLIPBOARD_ATTACHMENTS) return null;
  }
  return paths.length ? paths : null;
}

/** Convert only an all-path Windows paste into references; never evaluates shell syntax. */
export function parsePurePathDrop(text: string): ClipboardAttachment[] | null {
  const trimmed = text.trim();
  if (!trimmed || trimmed.includes("`") || trimmed.includes("\u001b")) return null;
  const lines = trimmed.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (!lines.length) return null;

  const paths: string[] = [];
  for (const line of lines) {
    const parsed = parsePathLine(line);
    if (!parsed) return null;
    paths.push(...parsed);
  }
  return paths.map((path) => ({ path, name: path.split(/[\\/]/).filter(Boolean).at(-1) || path }));
}

/**
 * Path parsing is deliberately separate from filesystem access. Only convert
 * the complete paste when every local drive path currently names a regular
 * file; a missing path remains ordinary composer text.
 */
export async function resolveExistingPathDrop(
  text: string,
  statPath: (path: string) => Promise<{ isFile(): boolean }> = async (path) => statFile(path),
): Promise<ClipboardAttachment[] | null> {
  const candidates = parsePurePathDrop(text);
  if (!candidates) return null;
  try {
    const stats = await Promise.all(candidates.map(({ path }) => statPath(path)));
    return stats.every((info) => info.isFile()) ? candidates : null;
  } catch {
    return null;
  }
}

function decodeClipboardCaptureOutput(output: string): ClipboardCaptureResult {
  let value: unknown;
  try {
    value = JSON.parse(output);
  } catch {
    throw new Error("剪贴板 helper 返回了无效 JSON");
  }
  if (!value || typeof value !== "object") throw new Error("剪贴板 helper 返回格式无效");
  const row = value as Record<string, unknown>;
  const kind = row.kind;
  if (kind !== "text" && kind !== "attachments" && kind !== "empty" && kind !== "error") {
    throw new Error("剪贴板 helper 返回了未知结果类型");
  }
  if (typeof row.text !== "string") throw new Error("剪贴板 helper 缺少 text 字段");
  const text = row.text;
  const attachments = validateClipboardAttachments(row.attachments);
  if (kind === "error") {
    const message = typeof row.error === "string" && row.error.trim()
      ? row.error.trim()
      : "剪贴板读取失败";
    return { kind, text, attachments, error: message };
  }
  if (kind === "attachments" && attachments.length === 0) {
    throw new Error("剪贴板 helper 声明有附件，但没有合法附件项");
  }
  if (kind !== "attachments" && attachments.length > 0) {
    throw new Error("剪贴板 helper 的结果类型与附件列表不一致");
  }
  if (kind === "empty" && text.length > 0) {
    throw new Error("剪贴板 helper 的空结果包含文本");
  }
  return { kind, text, attachments };
}

export function parseClipboardCaptureOutput(output: string): ClipboardCaptureResult {
  const result = decodeClipboardCaptureOutput(output);
  if (result.kind === "error") throw new Error(result.error || "剪贴板读取失败");
  return result;
}

async function readBoundedStdout(stream: ReadableStream<Uint8Array>): Promise<string> {
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      size += next.value.byteLength;
      if (size > MAX_HELPER_OUTPUT_BYTES) throw new Error("剪贴板 helper 输出超过上限");
      chunks.push(next.value);
    }
  } finally {
    reader.releaseLock();
  }
  const joined = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    joined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(joined);
}

function abortError(): Error {
  const error = new Error("剪贴板读取已取消");
  error.name = "AbortError";
  return error;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, ms));
}

async function terminateClipboardHelper(child: ClipboardHelperChild): Promise<void> {
  if (process.platform === "win32") {
    try {
      child.kill();
    } catch {
      // It may already have exited.
    }
  } else {
    // The helper owns a dedicated POSIX session/process group; never kill by
    // executable name or signal a group not created for this one-shot request.
    try {
      process.kill(-child.pid, "SIGTERM");
    } catch {
      // The process group may already be gone.
    }
    await delay(100);
    try {
      process.kill(-child.pid, "SIGKILL");
    } catch {
      // The process group may already be gone.
    }
  }
  await child.exited;
}

export async function captureClipboard(signal?: AbortSignal): Promise<ClipboardCaptureResult> {
  if (captureOverrideForTests) return captureOverrideForTests(signal);
  if (signal?.aborted) throw abortError();

  const projectRoot = resolve(process.env.RXYCODE_PROJECT_ROOT || SOURCE_PROJECT_ROOT);
  const helperPath = resolve(projectRoot, "utils", "clipboard_capture.py");
  const python = process.env.RXYCODE_APPSERVER_PYTHON?.trim() || "python";
  const command = [python, "-I", "-X", "utf8", helperPath];
  const child: ClipboardHelperChild = clipboardSpawnOverrideForTests
    ? clipboardSpawnOverrideForTests(command)
    : Bun.spawn(command, {
        cwd: projectRoot,
        stdout: "pipe",
        stderr: "ignore",
        ...(process.platform === "win32" ? {} : { detached: true }),
      });
  const outputTask = readBoundedStdout(child.stdout);
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  let rejectAbort: ((reason: Error) => void) | undefined;
  const abortPromise = new Promise<never>((_resolve, reject) => {
    rejectAbort = reject;
  });
  const onAbort = () => rejectAbort?.(abortError());
  signal?.addEventListener("abort", onAbort, { once: true });
  const timeoutPromise = new Promise<never>((_resolve, reject) => {
    timeoutId = setTimeout(() => reject(new Error("剪贴板 helper 超时（3.5 秒）")), HELPER_TIMEOUT_MS);
  });

  let helperFinished = false;
  try {
    const [exitCode, output] = await Promise.race([
      Promise.all([child.exited, outputTask]).then((result) => {
        helperFinished = true;
        return result;
      }),
      timeoutPromise,
      abortPromise,
    ]);
    if (exitCode !== 0) {
      let parsed: ClipboardCaptureResult;
      try {
        parsed = decodeClipboardCaptureOutput(output);
      } catch {
        throw new Error(`剪贴板 helper 退出码 ${exitCode}`);
      }
      if (parsed.kind === "error") throw new Error(parsed.error || "剪贴板读取失败");
      throw new Error(`剪贴板 helper 退出码 ${exitCode}`);
    }
    return parseClipboardCaptureOutput(output);
  } catch (error) {
    if (!helperFinished) await terminateClipboardHelper(child);
    await Promise.allSettled([child.exited, outputTask]);
    throw error;
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
    signal?.removeEventListener("abort", onAbort);
  }
}

export function formatAttachmentLabels(attachments: readonly ClipboardAttachment[]): string[] {
  return attachments.map((attachment, index) =>
    `${index + 1}. ${getAttachmentName(attachment)} · ${getAttachmentKind(attachment)}`,
  );
}
