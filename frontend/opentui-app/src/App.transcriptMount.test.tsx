import { afterAll, describe, expect, mock, test } from "bun:test";
import type { BaseRenderable, ScrollBoxRenderable } from "@opentui/core";
import { testRender } from "@opentui/react/test-utils";
import { act } from "react";
import type { ChatMessage } from "./types.ts";
import type { ChatTransport } from "./transport/types.ts";

process.env.RXYCODE_TRANSPORT = "http";
process.env.RXYCODE_API_URL = "http://127.0.0.1:9";
process.env.RXYCODE_API_TOKEN = "synthetic-test-token";

const fixtureMessages: ChatMessage[] = Array.from({ length: 1_000 }, (_, index) => {
  if (index === 999) {
    return {
      id: `fixture-${index}`,
      role: "tool",
      toolName: "write_file",
      toolArgs: JSON.stringify({ path: "plan.md" }),
      toolStatus: "success",
      toolExpanded: true,
      content: `fixture-${index}\n# Plan\n- Keep this synthetic plan card mounted.`,
      timestamp: index,
      done: true,
    };
  }
  if (index % 5 === 0) {
    return {
      id: `fixture-${index}`,
      role: "user",
      content: `fixture-${index}: inspect a synthetic module; no private content.`,
      timestamp: index,
    };
  }
  if (index % 5 === 1) {
    return {
      id: `fixture-${index}`,
      role: "assistant",
      content: `## Analysis ${index}\n\nA **synthetic** answer with a short table.\n\n| item | status |\n| --- | --- |\n| ${index} | verified |\n\n\`\`\`ts\nconst fixture = ${index};\n\`\`\``,
      timestamp: index,
      done: true,
    };
  }
  if (index % 5 === 2) {
    return {
      id: `fixture-${index}`,
      role: "tool",
      toolName: "bash",
      toolArgs: JSON.stringify({ command: `echo fixture-${index}` }),
      toolStatus: "success",
      toolExpanded: true,
      content: `fixture-${index}\n${"A short generated tool output line.\n".repeat(6)}`,
      timestamp: index,
      done: true,
    };
  }
  if (index % 5 === 3) {
    return {
      id: `fixture-${index}`,
      role: "thinking",
      content: `Expanded synthetic thought for fixture-${index}.`,
      expanded: true,
      timestamp: index,
      done: true,
    };
  }
  return {
    id: `fixture-${index}`,
    role: "child_session",
    content: `Synthetic child summary for fixture-${index}.`,
    agentId: "worker",
    childStatus: "completed",
    childSessionId: `child-${index}`,
    timestamp: index,
    done: true,
  };
});

const axiosGet = mock(async () => ({
  data: { models: [{ id: "synthetic/a", name: "synthetic/a" }], active: "synthetic/a" },
}));
const axiosPost = mock(async () => ({ data: { ok: true } }));
mock.module("axios", () => ({
  default: {
    get: axiosGet,
    post: axiosPost,
    isAxiosError: () => false,
  },
}));

const { __setChatTransportForTests, resetChatTransportForTests } = await import("./transport/index.ts");
const transport = {
  kind: "http",
  fetchStatus: async (onStatus: (status: { model: string; mode: "build"; context_used_k: number; context_max_k: number }) => void) => {
    onStatus({ model: "synthetic/a", mode: "build", context_used_k: 1, context_max_k: 256 });
  },
  sendCommand: async () => ({ ok: true, permission_mode: "auto_edit" }),
  cancelActiveRequest: async () => {},
  steerTurn: async () => ({ ok: true as const }),
  respondApproval: async () => true,
  respondQuestion: async () => true,
  sendChatMessage: async () => {},
  invokeSubagent: async () => { throw new Error("not used by transcript test"); },
  listChildSessions: async () => [],
  openChildSession: async () => ({ ok: false, message: "not used" }),
  openParentSession: async () => ({ ok: false, message: "not used" }),
  listSessions: async () => [{
    session_id: "synthetic-memory",
    display_title: "Synthetic memory benchmark",
    date_group: "Today",
  }],
  attachSession: async () => ({ session_id: "synthetic-memory", messages: fixtureMessages }),
  renameSession: async () => ({ session_id: "synthetic-memory" }),
  trashSession: async () => {},
  pinSession: async () => {},
  forkSession: async () => ({ session_id: "unused" }),
} satisfies ChatTransport;

__setChatTransportForTests(transport);
const { DialogProvider } = await import("./dialog/DialogHost.tsx");
const { default: App } = await import("./App.tsx");

function findScrollBox(node: BaseRenderable): ScrollBoxRenderable | undefined {
  if (node.constructor?.name === "ScrollBoxRenderable") {
    return node as ScrollBoxRenderable;
  }
  for (const child of node.getChildren()) {
    const found = findScrollBox(child);
    if (found) return found;
  }
  return undefined;
}

function countRenderableTree(node: BaseRenderable): number {
  return 1 + node.getChildren().reduce((count, child) => count + countRenderableTree(child), 0);
}

function hasRenderableClass(node: BaseRenderable, className: string): boolean {
  return node.constructor?.name === className || node.getChildren().some((child) =>
    hasRenderableClass(child, className),
  );
}

function messageRows(scrollBox: ScrollBoxRenderable) {
  return scrollBox.content.getChildren().filter((child) =>
    child.id.startsWith("transcript-message-"),
  );
}

async function typeCommand(
  mockInput: { typeText: (text: string) => Promise<void>; pressEnter: () => void },
  flush: () => Promise<void>,
  command: string,
): Promise<void> {
  await act(async () => {
    await mockInput.typeText(command);
    await flush();
    mockInput.pressEnter();
    await flush();
  });
}

async function pressAndFlush(
  mockInput: { pressKey: (key: string) => void },
  flush: () => Promise<void>,
  key: string,
): Promise<void> {
  await act(async () => {
    mockInput.pressKey(key);
    await flush();
    await new Promise((resolve) => setTimeout(resolve, 1));
    await flush();
  });
}

describe("App transcript mount integration", () => {
  afterAll(() => {
    resetChatTransportForTests();
  });

  test("attaches real history, pages by keyboard, keeps /copy complete, and releases mounts at tail/clear", async () => {
    const ui = await testRender(
      <DialogProvider><App /></DialogProvider>,
      { width: 120, height: 40 },
    );
    const copied: string[] = [];
    const originalCopy = ui.renderer.copyToClipboardOSC52.bind(ui.renderer);
    ui.renderer.copyToClipboardOSC52 = (text: string) => {
      copied.push(text);
      return true;
    };

    try {
      await act(async () => { await ui.flush(); });
      await typeCommand(ui.mockInput, ui.flush, "/session");
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 120));
        await ui.flush();
      });
      expect(ui.captureCharFrame()).toContain("Synthetic memory benchmark");
      await act(async () => {
        ui.mockInput.pressEnter();
        await new Promise((resolve) => setTimeout(resolve, 300));
        await ui.flush();
      });

      let scrollBox = findScrollBox(ui.renderer.root);
      expect(scrollBox).toBeTruthy();
      if (!scrollBox) return;
      expect(ui.captureCharFrame()).toContain("Wrote plan.md");
      expect(scrollBox.viewport.screenY).toBeGreaterThan(0);
      expect(hasRenderableClass(ui.renderer.root, "TextareaRenderable")).toBe(true);
      expect(messageRows(scrollBox)).toHaveLength(80);
      const initialIds = messageRows(scrollBox).map((row) => row.id);
      const firstMountedIndex = Number(initialIds[0]?.slice("transcript-message-".length));
      expect(firstMountedIndex).toBeGreaterThanOrEqual(920);
      expect(firstMountedIndex).toBeLessThanOrEqual(921);
      expect(scrollBox.content.getRenderable("transcript-message-0")).toBeUndefined();
      expect(countRenderableTree(scrollBox.content)).toBeLessThan(4_000);

      const initialScrollBox = scrollBox;
      await act(async () => {
        initialScrollBox.scrollTop = 0;
        await ui.flush();
      });
      const viewportTop = scrollBox.viewport.screenY;
      const viewportBottom = viewportTop + scrollBox.viewport.height;
      const anchor = messageRows(scrollBox).find((row) =>
        row.screenY + row.height > viewportTop && row.screenY < viewportBottom,
      );
      expect(anchor).toBeTruthy();
      if (!anchor) return;
      const anchorId = anchor.id;
      const anchorScreenY = anchor.screenY;

      await pressAndFlush(ui.mockInput, ui.flush, "\u001b[5~");
      expect(scrollBox.content.getRenderable("transcript-message-881")).toBeTruthy();
      expect(scrollBox.content.getRenderable("transcript-message-999")).toBeUndefined();
      expect(messageRows(scrollBox)).toHaveLength(80);
      // The anchor correction runs on a setTimeout(0) macrotask after commit
      // (scheduleViewportCorrection); under CI load it can lag the 1ms settle
      // in pressAndFlush, so poll briefly instead of reading one stale frame.
      {
        const deadline = Date.now() + 2_000;
        let observedY = scrollBox.content.getRenderable(anchorId)?.screenY;
        while (observedY !== anchorScreenY && Date.now() < deadline) {
          await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 25));
            await ui.flush();
          });
          observedY = scrollBox.content.getRenderable(anchorId)?.screenY;
        }
        expect(observedY).toBe(anchorScreenY);
      }

      await typeCommand(ui.mockInput, ui.flush, "/copy");
      expect(copied).toHaveLength(1);
      expect(copied[0]).toContain("fixture-0");
      expect(copied[0]).toContain("fixture-999");
      expect(copied[0]).toContain("[思考]");
      expect(copied[0]).toContain("[子代理 worker]");

      for (let page = 0; page < 23; page += 1) {
        await pressAndFlush(ui.mockInput, ui.flush, "\u001b[5~");
      }
      expect(scrollBox.content.getRenderable("transcript-message-0")).toBeTruthy();
      expect(messageRows(scrollBox)).toHaveLength(80);

      for (let page = 0; page < 24; page += 1) {
        await pressAndFlush(ui.mockInput, ui.flush, "\u001b[6~");
      }
      scrollBox = findScrollBox(ui.renderer.root)!;
      expect(scrollBox.content.getRenderable("transcript-message-999")).toBeTruthy();
      expect(scrollBox.content.getRenderable("transcript-message-0")).toBeUndefined();
      expect(messageRows(scrollBox)).toHaveLength(80);
      expect(countRenderableTree(scrollBox.content)).toBeLessThan(4_000);

      await typeCommand(ui.mockInput, ui.flush, "/clear");
      scrollBox = findScrollBox(ui.renderer.root)!;
      expect(messageRows(scrollBox)).toHaveLength(0);
    } finally {
      ui.renderer.copyToClipboardOSC52 = originalCopy;
      ui.renderer.destroy();
    }
  }, 30_000);
});
