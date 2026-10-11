import { describe, expect, test } from "bun:test";
import { act, createRef, useRef, useState, type RefObject } from "react";
import type { BaseRenderable, ScrollBoxRenderable } from "@opentui/core";
import { useKeyboard } from "@opentui/react";
import { testRender } from "@opentui/react/test-utils";
import { TranscriptMountWindow, type TranscriptMountWindowHandle } from "./TranscriptMountWindow.tsx";
import {
  DEFAULT_TRANSCRIPT_MOUNT_BUDGET,
  TRANSCRIPT_HISTORY_PAGE_SIZE,
  formatAllMessagesForCopy,
  newerTranscriptRange,
  olderTranscriptRange,
  tailTranscriptRange,
} from "./transcriptMountBudget.ts";
import type { ChatMessage } from "./types.ts";

const PAGE_UP = "\u001b[5~";
const PAGE_DOWN = "\u001b[6~";

function makeMessages(session: string, count: number): ChatMessage[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `${session}-${String(index).padStart(4, "0")}`,
    role: "user" as const,
    content: `${session}-${String(index).padStart(4, "0")}`,
    timestamp: index,
  }));
}

function countRenderableTree(renderable: BaseRenderable): number {
  return 1 + renderable.getChildren().reduce(
    (count, child) => count + countRenderableTree(child),
    0,
  );
}

function messageRenderables(scrollBox: ScrollBoxRenderable) {
  return scrollBox.content.getChildren().filter((child) =>
    child.id.startsWith("transcript-message-"),
  );
}

function TranscriptFixture({
  initialMessages,
  onCopy,
  scrollRef,
}: {
  initialMessages: ChatMessage[];
  onCopy: (text: string) => void;
  scrollRef: RefObject<ScrollBoxRenderable | null>;
}) {
  const [messages, setMessages] = useState(initialMessages);
  const [session, setSession] = useState("A");
  const [followingTail, setFollowingTail] = useState(true);
  const controlsRef = useRef<TranscriptMountWindowHandle | null>(null);

  useKeyboard((key) => {
    if (key.name === "pageup") {
      setFollowingTail(false);
      controlsRef.current?.loadOlder();
    } else if (key.name === "pagedown") {
      const reachesTail = controlsRef.current?.loadNewer() ?? true;
      setFollowingTail(reachesTail);
      if (reachesTail && scrollRef.current) {
        scrollRef.current.scrollTop = Math.max(0, scrollRef.current.scrollHeight);
      }
    } else if (key.name === "s") {
      setMessages(makeMessages("B", 150));
      setSession("B");
      setFollowingTail(true);
    } else if (key.name === "x") {
      setMessages([]);
      setSession("C");
      setFollowingTail(true);
    } else if (key.name === "t") {
      setMessages((current) => [
        ...current,
        {
          id: `stream-${current.length}`,
          role: "assistant",
          content: `stream-${current.length}`,
          timestamp: current.length,
          done: false,
        },
      ]);
    } else if (key.name === "c" && key.ctrl) {
      onCopy(formatAllMessagesForCopy(messages));
    }
  });

  return (
    <box style={{ flexDirection: "column", width: "100%", height: "100%" }}>
      <text>header outside the transcript viewport</text>
      <scrollbox
        ref={scrollRef}
        stickyScroll={followingTail}
        stickyStart="bottom"
        flexGrow={1}
        style={{
          rootOptions: { flexGrow: 1, border: false },
          viewportOptions: { flexGrow: 1 },
          contentOptions: {
            flexGrow: 1,
            flexDirection: "column",
            justifyContent: "flex-end",
          },
        }}
      >
        <TranscriptMountWindow
          messages={messages}
          resetKey={session}
          followingTail={followingTail}
          scrollRef={scrollRef}
          controlsRef={controlsRef}
          onHistoryNavigation={setFollowingTail}
          renderMessage={(message) => <text>{message.content}</text>}
        />
      </scrollbox>
      <text>
        {messages.length > DEFAULT_TRANSCRIPT_MOUNT_BUDGET && "history-loaded"}
      </text>
    </box>
  );
}

async function pressAndFlush(
  mockInput: { pressKey: (key: string, modifiers?: { ctrl?: boolean }) => void },
  flush: () => Promise<void>,
  key: string,
  modifiers?: { ctrl?: boolean },
): Promise<void> {
  await act(async () => {
    mockInput.pressKey(key, modifiers);
    await flush();
  });
}

describe("transcript mount budget", () => {
  test("uses a bounded overlapping tail-first sliding range", () => {
    const tail = tailTranscriptRange(1_000);
    expect(tail).toEqual({ start: 920, end: 1_000 });

    const older = olderTranscriptRange(tail, 1_000);
    expect(older).toEqual({ start: 880, end: 960 });
    expect(newerTranscriptRange(older, 1_000)).toEqual(tail);

    let range = tail;
    for (let page = 0; page < 100; page += 1) {
      range = olderTranscriptRange(range, 1_000);
      expect(range.end - range.start).toBeLessThanOrEqual(DEFAULT_TRANSCRIPT_MOUNT_BUDGET);
    }
    expect(range.start).toBe(0);
    expect(range.end).toBe(DEFAULT_TRANSCRIPT_MOUNT_BUDGET);
    expect(TRANSCRIPT_HISTORY_PAGE_SIZE).toBeLessThan(DEFAULT_TRANSCRIPT_MOUNT_BUDGET);
  });

  test("copy formatting still reads the complete transcript, including non-mounted roles", () => {
    const messages = makeMessages("copy", 1_000);
    messages[1] = { ...messages[1]!, role: "tool", toolName: "read", toolStatus: "success", toolArgs: "file.ts" };
    messages[2] = { ...messages[2]!, role: "thinking" };
    messages[3] = { ...messages[3]!, role: "child_session", agentId: "worker" };
    const copied = formatAllMessagesForCopy(messages);
    expect(copied).toContain("> copy-0000");
    expect(copied).toContain("[read success] file.ts copy-0001");
    expect(copied).toContain("[思考] copy-0002");
    expect(copied).toContain("[子代理 worker] copy-0003");
    expect(copied).toContain("> copy-0999");
  });
});

describe("TranscriptMountWindow with OpenTUI testRender", () => {
  test("PageUp pages across 1,000 records without growing native mounts; PageDown releases old rows", async () => {
    const scrollRef = createRef<ScrollBoxRenderable>();
    const { mockInput, mockMouse, flush, renderer } = await testRender(
      <TranscriptFixture initialMessages={makeMessages("A", 1_000)} onCopy={() => {}} scrollRef={scrollRef} />,
      { width: 80, height: 18 },
    );
    try {
      await flush();
      const scrollBox = scrollRef.current;
      expect(scrollBox).toBeTruthy();
      if (!scrollBox) return;

      const initialRows = messageRenderables(scrollBox);
      expect(initialRows).toHaveLength(DEFAULT_TRANSCRIPT_MOUNT_BUDGET);
      expect(scrollBox.content.getRenderable("transcript-message-920")).toBeTruthy();
      expect(scrollBox.content.getRenderable("transcript-message-0")).toBeUndefined();
      const initialNativeCount = countRenderableTree(scrollBox.content);
      expect(initialNativeCount).toBeLessThanOrEqual(DEFAULT_TRANSCRIPT_MOUNT_BUDGET * 4 + 16);

      await act(async () => {
        scrollBox.scrollTop = 0;
        await flush();
      });
      const olderButton = scrollBox.content.getRenderable("transcript-window-older");
      expect(olderButton).toBeTruthy();
      if (!olderButton) return;
      await act(async () => {
        await mockMouse.click(5, olderButton.screenY);
        await flush();
      });
      expect(scrollBox.content.getRenderable("transcript-message-880")).toBeTruthy();

      for (let page = 0; page < 8; page += 1) {
        await pressAndFlush(mockInput, flush, PAGE_UP);
      }
      expect(scrollBox.content.getRenderable("transcript-message-560")).toBeTruthy();
      expect(scrollBox.content.getRenderable("transcript-message-640")).toBeUndefined();
      expect(messageRenderables(scrollBox)).toHaveLength(DEFAULT_TRANSCRIPT_MOUNT_BUDGET);
      expect(countRenderableTree(scrollBox.content)).toBeLessThanOrEqual(DEFAULT_TRANSCRIPT_MOUNT_BUDGET * 4 + 16);

      for (let page = 0; page < 23; page += 1) {
        await pressAndFlush(mockInput, flush, PAGE_UP);
      }
      expect(scrollBox.content.getRenderable("transcript-message-0")).toBeTruthy();
      expect(messageRenderables(scrollBox)).toHaveLength(DEFAULT_TRANSCRIPT_MOUNT_BUDGET);

      for (let page = 0; page < 23; page += 1) {
        await pressAndFlush(mockInput, flush, PAGE_DOWN);
      }
      expect(scrollBox.content.getRenderable("transcript-message-999")).toBeTruthy();
      expect(scrollBox.content.getRenderable("transcript-message-0")).toBeUndefined();
      expect(messageRenderables(scrollBox)).toHaveLength(DEFAULT_TRANSCRIPT_MOUNT_BUDGET);
      expect(countRenderableTree(scrollBox.content)).toBeLessThanOrEqual(DEFAULT_TRANSCRIPT_MOUNT_BUDGET * 4 + 16);
    } finally {
      renderer.destroy();
    }
  }, 20_000);

  test("older-page anchor is preserved; streaming stays historical; session switch and clear reset the window", async () => {
    let copied = "";
    const scrollRef = createRef<ScrollBoxRenderable>();
    const { mockInput, flush, renderer } = await testRender(
      <TranscriptFixture
        initialMessages={makeMessages("A", 1_000)}
        onCopy={(text) => { copied = text; }}
        scrollRef={scrollRef}
      />,
      { width: 80, height: 18 },
    );
    try {
      await flush();
      const scrollBox = scrollRef.current;
      expect(scrollBox).toBeTruthy();
      if (!scrollBox) return;

      await act(async () => {
        scrollBox.scrollTop = 60;
        await flush();
      });
      const beforeRows = messageRenderables(scrollBox);
      const beforeAnchor = beforeRows.find(
        (row) => row.screenY + row.height > scrollBox.viewport.screenY &&
          row.screenY < scrollBox.viewport.screenY + scrollBox.viewport.height,
      );
      expect(beforeAnchor).toBeTruthy();
      if (!beforeAnchor) return;
      const anchorIndex = Number(beforeAnchor.id.slice("transcript-message-".length));
      expect(anchorIndex).toBeGreaterThanOrEqual(920);
      expect(anchorIndex).toBeLessThan(960);
      const oldScreenY = beforeAnchor.screenY;

      await pressAndFlush(mockInput, flush, PAGE_UP);
      const anchoredRow = scrollBox.content.getRenderable(`transcript-message-${anchorIndex}`);
      expect(anchoredRow).toBeTruthy();
      if (anchoredRow) {
        expect(anchoredRow.screenY).toBe(oldScreenY);
      }

      await pressAndFlush(mockInput, flush, "t");
      expect(scrollBox.content.getRenderable("transcript-message-960")).toBeUndefined();
      const afterStreamAnchor = scrollBox.content.getRenderable(`transcript-message-${anchorIndex}`);
      expect(afterStreamAnchor).toBeTruthy();
      expect(messageRenderables(scrollBox)).toHaveLength(DEFAULT_TRANSCRIPT_MOUNT_BUDGET);
      expect(messageRenderables(scrollBox)[0]?.id).toBe("transcript-message-880");
      expect(scrollBox.scrollTop).toBeLessThan(scrollBox.scrollHeight - scrollBox.viewport.height);

      await pressAndFlush(mockInput, flush, "s");
      expect(scrollBox.content.getRenderable("transcript-message-149")).toBeTruthy();
      expect(scrollBox.content.getRenderable("transcript-message-150")).toBeUndefined();

      await pressAndFlush(mockInput, flush, "c", { ctrl: true });
      expect(copied).toContain("> B-0000");
      expect(copied).toContain("> B-0149");
      expect(copied).not.toContain("A-0000");

      await pressAndFlush(mockInput, flush, "x");
      expect(messageRenderables(scrollBox)).toHaveLength(0);
    } finally {
      renderer.destroy();
    }
  }, 20_000);
});
