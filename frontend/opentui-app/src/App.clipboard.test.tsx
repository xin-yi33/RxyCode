import { afterEach, describe, expect, mock, test } from "bun:test";
import { parseKeypress } from "@opentui/core";
import { testRender } from "@opentui/react/test-utils";
import { act } from "react";
import type { ChatTransport } from "./transport/types.ts";
import type { ClipboardAttachment, ClipboardCaptureResult } from "./clipboard.ts";

process.env.RXYCODE_TRANSPORT = "http";
process.env.RXYCODE_API_URL = "http://127.0.0.1:9";
process.env.RXYCODE_API_TOKEN = "synthetic-test-token";

let httpStatusCapabilities: Record<string, unknown> | undefined = { prompt_attachments: true };
const axiosGet = mock(async (url: string) => ({
  data: url.endsWith("/status")
    ? { capabilities: httpStatusCapabilities }
    : { models: [{ id: "synthetic/a", name: "synthetic/a" }] },
}));
mock.module("axios", () => ({
  default: {
    get: axiosGet,
    post: mock(async () => ({ data: { ok: true } })),
    isAxiosError: () => false,
  },
}));

const { __setChatTransportForTests, resetChatTransportForTests } = await import("./transport/index.ts");
const { httpTransport } = await import("./transport/httpTransport.ts");
const { __setClipboardCaptureForTests } = await import("./clipboard.ts");
const { DialogProvider } = await import("./dialog/DialogHost.tsx");
const { default: App } = await import("./App.tsx");
const originalFetch = globalThis.fetch;

function makeTransport(
  sendChatMessage: ChatTransport["sendChatMessage"],
  getCurrentSessionId: () => string | null = () => "native-clipboard-session",
): ChatTransport {
  return {
    kind: "http",
    getCurrentSessionId,
    fetchStatus: async (onStatus) => {
      onStatus({ model: "synthetic/a", mode: "build", context_used_k: 1, context_max_k: 64 });
    },
    sendCommand: async () => ({ ok: true, permission_mode: "auto_edit" }),
    cancelActiveRequest: async () => {},
    steerTurn: async () => ({ ok: true }),
    respondApproval: async () => true,
    respondQuestion: async () => true,
    sendChatMessage,
    invokeSubagent: async () => { throw new Error("not used"); },
    listChildSessions: async () => [],
    openChildSession: async () => ({ ok: false, message: "not used" }),
    openParentSession: async () => ({ ok: false, message: "not used" }),
    listSessions: async () => [{
      session_id: "native-clipboard-session",
      display_title: "Native clipboard test session",
      date_group: "Today",
    }],
    attachSession: async () => ({ session_id: "native-clipboard-session", messages: [] }),
    renameSession: async () => ({ session_id: "native-clipboard-session" }),
    trashSession: async () => {},
    pinSession: async () => {},
    forkSession: async () => ({ session_id: "native-clipboard-fork" }),
  };
}

async function settle(ui: { flush: () => Promise<void> }, delayMs = 20): Promise<void> {
  await act(async () => {
    await ui.flush();
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    await ui.flush();
  });
}

async function typeCommand(
  ui: {
    mockInput: { typeText: (text: string) => Promise<void>; pressEnter: () => void };
    flush: () => Promise<void>;
  },
  command: string,
): Promise<void> {
  await act(async () => {
    await ui.mockInput.typeText(command);
    await ui.flush();
    ui.mockInput.pressEnter();
    await ui.flush();
  });
  await settle(ui);
}

afterEach(() => {
  __setClipboardCaptureForTests(null);
  resetChatTransportForTests();
  httpStatusCapabilities = { prompt_attachments: true };
  globalThis.fetch = originalFetch;
});

describe("App native clipboard attachment interaction", () => {
  test("raw ESC+v is parsed as legacy Alt and triggers capture, while other Meta keys do not", async () => {
    let helperCalls = 0;
    __setChatTransportForTests(makeTransport(async () => {}));
    __setClipboardCaptureForTests(async () => {
      helperCalls += 1;
      return {
        kind: "attachments",
        text: "",
        attachments: [{ path: "C:\\fixtures\\terminal-alt.png", name: "terminal-alt.png" }],
      };
    });
    const ui = await testRender(<DialogProvider><App /></DialogProvider>, { width: 80, height: 32 });
    try {
      await settle(ui);
      const parsed = parseKeypress("\u001bv");
      expect(parsed).toMatchObject({ name: "v", meta: true, option: false, raw: "\u001bv" });

      await act(async () => {
        await ui.mockInput.pressKeys(["\u001bx"]);
        await ui.flush();
      });
      expect(helperCalls).toBe(0);

      await act(async () => {
        await ui.mockInput.pressKeys(["\u001bv"]);
        await ui.flush();
      });
      await settle(ui);
      expect(helperCalls).toBe(1);
      expect(ui.captureCharFrame()).toContain("terminal-alt.png");
    } finally {
      ui.renderer.destroy();
    }
  }, 30_000);

  test("older HTTP status without attachment capability rejects visibly and restores the draft", async () => {
    httpStatusCapabilities = undefined;
    let chatRequests = 0;
    globalThis.fetch = (async () => {
      chatRequests += 1;
      return new Response('data: {"type":"done"}\n\n', {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      });
    }) as unknown as typeof fetch;
    __setChatTransportForTests(httpTransport);
    __setClipboardCaptureForTests(async () => ({
      kind: "attachments",
      text: "",
      attachments: [{ path: "C:\\fixtures\\legacy.png", name: "legacy.png" }],
    }));

    const ui = await testRender(<DialogProvider><App /></DialogProvider>, { width: 80, height: 32 });
    try {
      await settle(ui);
      await typeCommand(ui, "/paste");
      await act(async () => {
        await ui.mockInput.typeText("inspect old server");
        await ui.flush();
        ui.mockInput.pressEnter();
        await ui.flush();
      });
      await settle(ui, 80);

      const frame = ui.captureCharFrame();
      expect(frame).toContain("inspect old server");
      expect(frame).toContain("legacy.png");
      expect(frame).toContain("prompt_attachments");
      expect(frame).toContain("附件草稿已保留");
      expect(chatRequests).toBe(0);
    } finally {
      ui.renderer.destroy();
    }
  }, 30_000);

  test("capture started before first session initialization accepts the initial session id", async () => {
    let currentSessionId: string | null = null;
    let resolveCapture!: (result: ClipboardCaptureResult) => void;
    let notifyHelperStarted!: () => void;
    const helperStarted = new Promise<void>((resolve) => { notifyHelperStarted = resolve; });
    __setChatTransportForTests(makeTransport(async () => {}, () => currentSessionId));
    __setClipboardCaptureForTests(() => new Promise((resolve) => {
      resolveCapture = resolve;
      notifyHelperStarted();
    }));
    const ui = await testRender(<DialogProvider><App /></DialogProvider>, { width: 80, height: 32 });
    try {
      await settle(ui);
      await typeCommand(ui, "/paste");
      await helperStarted;
      currentSessionId = "initialized-first-session";
      await act(async () => {
        resolveCapture({
          kind: "attachments",
          text: "",
          attachments: [{ path: "C:\\fixtures\\boot.png", name: "boot.png" }],
        });
        await ui.flush();
      });
      await settle(ui);
      expect(ui.captureCharFrame()).toContain("boot.png");
      expect(ui.captureCharFrame()).toContain("已添加 1 个附件");
    } finally {
      ui.renderer.destroy();
    }
  }, 30_000);

  test("capture rejects a late result when an initialized session changes", async () => {
    let currentSessionId: string | null = "session-before-capture";
    let resolveCapture!: (result: ClipboardCaptureResult) => void;
    let notifyHelperStarted!: () => void;
    const helperStarted = new Promise<void>((resolve) => { notifyHelperStarted = resolve; });
    __setChatTransportForTests(makeTransport(async () => {}, () => currentSessionId));
    __setClipboardCaptureForTests(() => new Promise((resolve) => {
      resolveCapture = resolve;
      notifyHelperStarted();
    }));
    const ui = await testRender(<DialogProvider><App /></DialogProvider>, { width: 80, height: 32 });
    try {
      await settle(ui);
      await typeCommand(ui, "/paste");
      await helperStarted;
      currentSessionId = "different-session";
      await act(async () => {
        resolveCapture({
          kind: "attachments",
          text: "",
          attachments: [{ path: "C:\\fixtures\\late.png", name: "late.png" }],
        });
        await ui.flush();
      });
      await settle(ui);
      expect(ui.captureCharFrame()).not.toContain("late.png");
    } finally {
      ui.renderer.destroy();
    }
  }, 30_000);

  test("capture ignores a late result after the composer draft changes", async () => {
    let resolveCapture!: (result: ClipboardCaptureResult) => void;
    let notifyHelperStarted!: () => void;
    const helperStarted = new Promise<void>((resolve) => { notifyHelperStarted = resolve; });
    __setChatTransportForTests(makeTransport(async () => {}));
    __setClipboardCaptureForTests(() => new Promise((resolve) => {
      resolveCapture = resolve;
      notifyHelperStarted();
    }));
    const ui = await testRender(<DialogProvider><App /></DialogProvider>, { width: 80, height: 32 });
    try {
      await settle(ui);
      await typeCommand(ui, "/paste");
      await helperStarted;
      await act(async () => {
        await ui.mockInput.typeText("edited draft");
        await ui.flush();
      });
      await act(async () => {
        resolveCapture({
          kind: "attachments",
          text: "",
          attachments: [{ path: "C:\\fixtures\\late.png", name: "late.png" }],
        });
        await ui.flush();
      });
      await settle(ui);
      expect(ui.captureCharFrame()).toContain("edited draft");
      expect(ui.captureCharFrame()).not.toContain("late.png");
    } finally {
      ui.renderer.destroy();
    }
  }, 30_000);

  test("/paste chips then admission rejection restores draft without retry", async () => {
    let helperCalls = 0;
    const attachment: ClipboardAttachment = {
      path: "C:\\fixtures\\diagram.png",
      name: "diagram.png",
    };
    const sent: Array<{ content: string; attachments?: readonly ClipboardAttachment[] }> = [];
    const sendChatMessage: ChatTransport["sendChatMessage"] = async (content, _mode, _callbacks, _signal, _display, attachments) => {
      sent.push({ content, attachments });
      throw new Error("unsupported-vision: selected model cannot accept image attachments");
    };
    __setChatTransportForTests(makeTransport(sendChatMessage));
    __setClipboardCaptureForTests(async () => {
      helperCalls += 1;
      return { kind: "attachments", text: "", attachments: [attachment] };
    });

    const ui = await testRender(<DialogProvider><App /></DialogProvider>, { width: 80, height: 32 });
    try {
      await settle(ui);
      await typeCommand(ui, "/paste");
      await settle(ui, 100);
      expect(helperCalls).toBe(1);
      expect(ui.captureCharFrame()).toContain("diagram.png");
      expect(ui.captureCharFrame()).toContain("image");

      await act(async () => {
        await ui.mockInput.typeText("请检查这张图");
        await ui.flush();
        ui.mockInput.pressEnter();
        await ui.flush();
      });
      await settle(ui, 80);

      expect(sent).toHaveLength(1);
      expect(sent[0]?.content).toBe("请检查这张图");
      expect(sent[0]?.attachments).toEqual([attachment]);
      const frame = ui.captureCharFrame();
      expect(frame).toContain("请检查这张图");
      expect(frame).toContain("diagram.png");
      expect(frame).toContain("unsupported-vision");
      expect(frame).toContain("未自动重试");
    } finally {
      ui.renderer.destroy();
    }
  }, 30_000);

  test("Ctrl+V bracketed URL remains literal text and does not invoke the helper", async () => {
    let helperCalls = 0;
    __setChatTransportForTests(makeTransport(async () => {}));
    __setClipboardCaptureForTests(async () => {
      helperCalls += 1;
      return { kind: "empty", text: "", attachments: [] };
    });
    const ui = await testRender(<DialogProvider><App /></DialogProvider>, { width: 80, height: 32 });
    try {
      await settle(ui);
      await act(async () => {
        ui.mockInput.pressKey("v", { ctrl: true });
        ui.mockInput.pasteBracketedText("https://example.com/diagram.png");
        await ui.flush();
      });
      expect(ui.captureCharFrame()).toContain("https://example.com/diagram.png");
      expect(ui.captureCharFrame()).toContain("Alt+V · /paste");
      expect(helperCalls).toBe(0);
    } finally {
      ui.renderer.destroy();
    }
  }, 30_000);

  test("a dialog owns bracketed paste and does not trigger composer capture", async () => {
    let helperCalls = 0;
    __setChatTransportForTests(makeTransport(async () => {}));
    __setClipboardCaptureForTests(async () => {
      helperCalls += 1;
      return { kind: "empty", text: "", attachments: [] };
    });
    const ui = await testRender(<DialogProvider><App /></DialogProvider>, { width: 80, height: 32 });
    try {
      await settle(ui);
      await typeCommand(ui, "/session");
      await act(async () => {
        ui.mockInput.pasteBracketedText("search text");
        await ui.flush();
      });
      expect(helperCalls).toBe(0);
      expect(ui.captureCharFrame()).toContain("Native clipboard test session");
    } finally {
      ui.renderer.destroy();
    }
  }, 30_000);

  test("/removeattachment removes the selected chip without affecting other draft text", async () => {
    __setChatTransportForTests(makeTransport(async () => {}));
    __setClipboardCaptureForTests(async () => ({
      kind: "attachments",
      text: "",
      attachments: [
        { path: "C:\\fixtures\\first.txt", name: "first.txt" },
        { path: "C:\\fixtures\\second.pdf", name: "second.pdf" },
      ],
    }));
    const ui = await testRender(<DialogProvider><App /></DialogProvider>, { width: 80, height: 32 });
    try {
      await settle(ui);
      await typeCommand(ui, "/paste");
      expect(ui.captureCharFrame()).toContain("first.txt");
      expect(ui.captureCharFrame()).toContain("second.pdf");
      await typeCommand(ui, "/removeattachment 1");
      const frame = ui.captureCharFrame();
      expect(frame).not.toContain("first.txt");
      expect(frame).toContain("second.pdf");
      expect(frame).toContain("已移除附件 1");
    } finally {
      ui.renderer.destroy();
    }
  }, 30_000);

  test("the compact chip row leaves the composer visible at 52 columns", async () => {
    __setChatTransportForTests(makeTransport(async () => {}));
    __setClipboardCaptureForTests(async () => ({
      kind: "attachments",
      text: "",
      attachments: [{ path: "C:\\fixtures\\photo.png", name: "photo.png" }],
    }));
    const ui = await testRender(<DialogProvider><App /></DialogProvider>, { width: 52, height: 26 });
    try {
      await settle(ui);
      await typeCommand(ui, "/paste");
      const frame = ui.captureCharFrame();
      expect(frame).toContain("photo.png");
      expect(frame).toContain("输入指令或需求...");
      expect(frame).toContain("已添加 1 个附件");
    } finally {
      ui.renderer.destroy();
    }
  }, 30_000);

  test("queued follow-up sends its own attachment metadata after the active turn", async () => {
    const sent: Array<{ content: string; attachments?: readonly ClipboardAttachment[] }> = [];
    const finishFirst: { current: (() => void) | null } = { current: null };
    const sendChatMessage: ChatTransport["sendChatMessage"] = async (content, _mode, callbacks, _signal, _display, attachments) => {
      sent.push({ content, attachments });
      if (sent.length === 1) {
        callbacks.onStreaming(true);
        await new Promise<void>((resolve) => {
          finishFirst.current = () => {
            callbacks.onStreaming(false);
            resolve();
          };
        });
      }
    };
    __setChatTransportForTests(makeTransport(sendChatMessage));
    let helperCalls = 0;
    __setClipboardCaptureForTests(async () => {
      helperCalls += 1;
      const name = helperCalls === 1 ? "first.txt" : "queued.pdf";
      return {
        kind: "attachments",
        text: "",
        attachments: [{ path: `C:\\fixtures\\${name}`, name }],
      };
    });
    const ui = await testRender(<DialogProvider><App /></DialogProvider>, { width: 80, height: 32 });
    try {
      await settle(ui);
      await typeCommand(ui, "/paste");
      await act(async () => {
        await ui.mockInput.typeText("first turn");
        await ui.flush();
        ui.mockInput.pressEnter();
        await ui.flush();
      });
      await settle(ui);
      expect(sent).toHaveLength(1);

      await typeCommand(ui, "/paste");
      expect(ui.captureCharFrame()).toContain("queued.pdf");
      await act(async () => {
        await ui.mockInput.typeText("queued follow-up");
        await ui.flush();
        ui.mockInput.pressEnter();
        await ui.flush();
      });
      await settle(ui);
      expect(ui.captureCharFrame()).toContain("已排队");
      expect(sent).toHaveLength(1);

      finishFirst.current?.();
      for (let attempt = 0; attempt < 20 && sent.length < 2; attempt += 1) await settle(ui, 10);
      expect(sent).toHaveLength(2);
      expect(sent[0]?.content).toBe("first turn");
      expect(sent[0]?.attachments).toEqual([{ path: "C:\\fixtures\\first.txt", name: "first.txt" }]);
      expect(sent[1]?.content).toBe("queued follow-up");
      expect(sent[1]?.attachments).toEqual([{ path: "C:\\fixtures\\queued.pdf", name: "queued.pdf" }]);
    } finally {
      finishFirst.current?.();
      ui.renderer.destroy();
    }
  }, 30_000);

  test("a missing dropped path stays literal composer text", async () => {
    const sendChatMessage: ChatTransport["sendChatMessage"] = async () => {};
    __setChatTransportForTests(makeTransport(sendChatMessage));
    let helperCalls = 0;
    __setClipboardCaptureForTests(async () => {
      helperCalls += 1;
      return { kind: "empty", text: "", attachments: [] };
    });
    const ui = await testRender(<DialogProvider><App /></DialogProvider>, { width: 80, height: 32 });
    try {
      await settle(ui);
      const missing = "C:\\new\\not-created-yet-app.py";
      await act(async () => {
        ui.mockInput.pasteBracketedText(missing);
        await ui.flush();
        await new Promise((resolve) => setTimeout(resolve, 50));
        await ui.flush();
      });
      expect(ui.captureCharFrame()).toContain(missing);
      expect(helperCalls).toBe(0);
    } finally {
      ui.renderer.destroy();
    }
  }, 30_000);
});
