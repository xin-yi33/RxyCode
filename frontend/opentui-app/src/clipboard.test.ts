import { describe, expect, test } from "bun:test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  __setClipboardSpawnForTests,
  MAX_CLIPBOARD_ATTACHMENTS,
  MAX_CLIPBOARD_PATH_LENGTH,
  captureClipboard,
  formatAttachmentLabels,
  getAttachmentName,
  parseClipboardCaptureOutput,
  parsePurePathDrop,
  resolveExistingPathDrop,
  validateClipboardAttachments,
} from "./clipboard.ts";

function capture(kind: string, attachments: unknown, text = "") {
  return JSON.stringify({ kind, text, attachments });
}

function fakeClipboardChild(exitCode: number, output: string) {
  const bytes = new TextEncoder().encode(output);
  return {
    pid: 987654,
    exited: Promise.resolve(exitCode),
    stdout: new ReadableStream<Uint8Array>({
      start(controller) {
        if (bytes.length) controller.enqueue(bytes);
        controller.close();
      },
    }),
    kill() {
      throw new Error("completed fake child should not be terminated");
    },
  };
}

describe("clipboard attachment parsing", () => {
  test("helper attachment output is all-or-none and rejects malformed items", () => {
    expect(() => parseClipboardCaptureOutput(capture("attachments", [
      { path: "C:\\ok.png", name: "ok.png" },
      { path: "   " },
    ]))).toThrow(/路径/);
    expect(() => parseClipboardCaptureOutput(capture("attachments", [null]))).toThrow(/附件项/);
    expect(() => parseClipboardCaptureOutput(capture("attachments", [{ path: "C:\\x.png", name: 42 }]))).toThrow(/名称/);
    expect(() => parseClipboardCaptureOutput(capture("attachments", []))).toThrow(/没有合法附件/);
  });

  test("nullable protocol names normalize to basename fallback instead of dropping the attachment", () => {
    const attachments = parseClipboardCaptureOutput(capture("attachments", [
      { path: "C:\\fixtures\\diagram.png", name: null },
    ])).attachments;
    expect(attachments).toEqual([{ path: "C:\\fixtures\\diagram.png" }]);
    expect(getAttachmentName(attachments[0]!)).toBe("diagram.png");
    expect(validateClipboardAttachments([{ path: "C:\\fixtures\\diagram.png", name: null }]))
      .toEqual([{ path: "C:\\fixtures\\diagram.png" }]);
  });

  test("display labels strip terminal controls while preserving original path and name metadata", () => {
    const rawAttachment = {
      path: "C:\\fixtures\\original.png",
      name: "\u001b]8;;https://example.invalid\u0007original\n\t\u001b[31m.png",
    };
    const validated = validateClipboardAttachments([rawAttachment]);
    const label = formatAttachmentLabels(validated)[0]!;

    expect(label).not.toMatch(/[\u0000-\u001F\u007F-\u009F\u2028\u2029]/);
    expect(label).not.toContain("\n");
    expect(validated).toEqual([rawAttachment]);
    expect(validated[0]?.path).toBe(rawAttachment.path);
    expect(validated[0]?.name).toBe(rawAttachment.name);
  });

  test("helper output enforces the attachment count and path bounds", () => {
    const ten = Array.from({ length: MAX_CLIPBOARD_ATTACHMENTS }, (_, i) => ({ path: `C:\\${i}.txt` }));
    expect(parseClipboardCaptureOutput(capture("attachments", ten)).attachments).toHaveLength(10);
    expect(() => parseClipboardCaptureOutput(capture("attachments", [...ten, { path: "C:\\extra.txt" }]))).toThrow(/最多/);
    expect(() => parseClipboardCaptureOutput(capture("attachments", [{ path: `C:\\${"x".repeat(MAX_CLIPBOARD_PATH_LENGTH)}` }]))).toThrow(/过长/);
  });

  test("nonzero helper exit surfaces a valid JSON error reason but never accepts success output", async () => {
    const rootError = "Windows CF_HDROP file list could not be read";
    __setClipboardSpawnForTests(() => fakeClipboardChild(1, JSON.stringify({
      kind: "error",
      text: "",
      attachments: [],
      error: rootError,
    })));
    try {
      await expect(captureClipboard()).rejects.toThrow(rootError);
    } finally {
      __setClipboardSpawnForTests(null);
    }

    __setClipboardSpawnForTests(() => fakeClipboardChild(7, capture("text", [], "must not be accepted")));
    try {
      await expect(captureClipboard()).rejects.toThrow("helper 退出码 7");
    } finally {
      __setClipboardSpawnForTests(null);
    }

    __setClipboardSpawnForTests(() => fakeClipboardChild(5, JSON.stringify({
      kind: "error",
      text: "",
      attachments: "invalid",
      error: rootError,
    })));
    try {
      await expect(captureClipboard()).rejects.toThrow("helper 退出码 5");
    } finally {
      __setClipboardSpawnForTests(null);
    }

    __setClipboardSpawnForTests(() => fakeClipboardChild(2, "not JSON"));
    try {
      await expect(captureClipboard()).rejects.toThrow("helper 退出码 2");
    } finally {
      __setClipboardSpawnForTests(null);
    }
  });

  test("capture uses isolated UTF-8 Python flags and the actual helper CLI accepts them", async () => {
    let command: string[] | undefined;
    __setClipboardSpawnForTests((argv) => {
      command = argv;
      return fakeClipboardChild(0, capture("empty", []));
    });
    try {
      await expect(captureClipboard()).resolves.toEqual({ kind: "empty", text: "", attachments: [] });
    } finally {
      __setClipboardSpawnForTests(null);
    }

    expect(command?.slice(1, 4)).toEqual(["-I", "-X", "utf8"]);
    expect(command?.[4]).toContain("utils");
    expect(command?.[4]).toEndWith("clipboard_capture.py");

    const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
    const helpChild = Bun.spawn([...command!, "--help"], {
      cwd: projectRoot,
      stdout: "pipe",
      stderr: "pipe",
    });
    const [exitCode, stdout, stderr] = await Promise.all([
      helpChild.exited,
      new Response(helpChild.stdout!).text(),
      new Response(helpChild.stderr!).text(),
    ]);
    expect(exitCode).toBe(0);
    expect(stdout).toContain("--output-dir");
    expect(stderr).toBe("");
  });

  test("path parser never turns backticks, UNC paths, URLs, or mixed prose into attachments", () => {
    expect(parsePurePathDrop("`C:\\src\\a.ts` ")).toBeNull();
    expect(parsePurePathDrop("\\\\server\\share\\a.png")).toBeNull();
    expect(parsePurePathDrop("https://example.com/image.png")).toBeNull();
    expect(parsePurePathDrop("引用 C:\\src\\a.ts 这段文字")).toBeNull();
    expect(parsePurePathDrop('"C:\\素材 文件\\图.png"\nD:\\code\\main.py')).toEqual([
      { path: "C:\\素材 文件\\图.png", name: "图.png" },
      { path: "D:\\code\\main.py", name: "main.py" },
    ]);
  });

  test("a nonexistent pure path remains text; all candidates must be regular files", async () => {
    const nonexistent = await resolveExistingPathDrop("C:\\new\\app.py", async () => {
      throw new Error("ENOENT");
    });
    expect(nonexistent).toBeNull();

    const mixed = await resolveExistingPathDrop('"C:\\exists one.png" D:\\missing.png', async (path) => ({
      isFile: () => path.includes("exists"),
    }));
    expect(mixed).toBeNull();

    const valid = await resolveExistingPathDrop('"C:\\exists one.png" D:\\exists-two.png', async () => ({
      isFile: () => true,
    }));
    expect(valid).toHaveLength(2);
  });
});
