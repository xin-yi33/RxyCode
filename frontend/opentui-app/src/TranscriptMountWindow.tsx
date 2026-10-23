import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import type { ScrollBoxRenderable } from "@opentui/core";
import type { ChatMessage } from "./types.ts";
import {
  DEFAULT_TRANSCRIPT_MOUNT_BUDGET,
  TRANSCRIPT_HISTORY_PAGE_SIZE,
  olderTranscriptRange,
  newerTranscriptRange,
  sameTranscriptRange,
  tailTranscriptRange,
  type TranscriptMountRange,
} from "./transcriptMountBudget.ts";

const MESSAGE_RENDERABLE_PREFIX = "transcript-message-";

type PendingViewport =
  | { kind: "anchor"; messageIndex: number; scrollTop: number; screenY: number; direction: "older" | "newer" }
  | { kind: "bottom" };

export interface TranscriptMountWindowHandle {
  loadOlder: () => boolean;
  /** Returns true when the resulting mounted window reaches the transcript tail. */
  loadNewer: () => boolean;
  resetToTail: () => void;
  getRange: () => TranscriptMountRange;
}

export interface TranscriptMountWindowProps {
  messages: readonly ChatMessage[];
  resetKey: string;
  followingTail: boolean;
  scrollRef: RefObject<ScrollBoxRenderable | null>;
  controlsRef?: RefObject<TranscriptMountWindowHandle | null>;
  onHistoryNavigation?: (atTail: boolean) => void;
  renderMessage: (message: ChatMessage, index: number) => ReactNode;
  mountBudget?: number;
  pageSize?: number;
}

function captureViewportAnchor(
  scrollRef: RefObject<ScrollBoxRenderable | null>,
): Extract<PendingViewport, { kind: "anchor" }> | null {
  const box = scrollRef.current;
  if (!box) return null;
  const scrollTop = box.scrollTop;
  const viewportTop = box.viewport.screenY;
  const viewportBottom = viewportTop + box.viewport.height;
  const visibleMessage = box.content.getChildren().find((child) => {
    if (!child.id.startsWith(MESSAGE_RENDERABLE_PREFIX)) return false;
    const childTop = child.screenY;
    const childBottom = childTop + child.height;
    return childBottom > viewportTop && childTop < viewportBottom;
  });
  if (!visibleMessage) return null;
  const messageIndex = Number(visibleMessage.id.slice(MESSAGE_RENDERABLE_PREFIX.length));
  if (!Number.isFinite(messageIndex)) return null;
  return {
    kind: "anchor",
    messageIndex,
    // Use screenY because the chat viewport can start below the app header/Todo
    // dock. It already reflects scrollTop and stays in the same coordinate
    // system as viewport.screenY when the page changes.
    scrollTop,
    screenY: visibleMessage.screenY,
    direction: "older",
  };
}

function scrollToBottom(box: ScrollBoxRenderable): void {
  box.scrollTop = Math.max(0, box.scrollHeight);
}

export function TranscriptMountWindow({
  messages,
  resetKey,
  followingTail,
  scrollRef,
  controlsRef,
  onHistoryNavigation,
  renderMessage,
  mountBudget = DEFAULT_TRANSCRIPT_MOUNT_BUDGET,
  pageSize = TRANSCRIPT_HISTORY_PAGE_SIZE,
}: TranscriptMountWindowProps) {
  const [windowState, setWindowState] = useState(() => ({
    resetKey,
    range: tailTranscriptRange(messages.length, mountBudget),
  }));
  const pendingViewportRef = useRef<PendingViewport | null>(null);
  const viewportTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleViewportCorrection = useCallback((correct: () => void) => {
    if (viewportTimerRef.current) clearTimeout(viewportTimerRef.current);
    // OpenTUI recalculates ScrollBar.scrollSize after Yoga lays out newly
    // mounted children. A correction during React's commit can be clamped
    // against the previous page's size, so apply it on the next turn.
    viewportTimerRef.current = setTimeout(() => {
      viewportTimerRef.current = null;
      correct();
    }, 0);
  }, []);
  const range = windowState.resetKey === resetKey
    ? windowState.range
    : tailTranscriptRange(messages.length, mountBudget);

  const loadOlder = useCallback(() => {
    const next = olderTranscriptRange(range, messages.length, mountBudget, pageSize);
    if (sameTranscriptRange(range, next)) return false;
    onHistoryNavigation?.(false);
    const anchor = captureViewportAnchor(scrollRef);
    pendingViewportRef.current = anchor
      ? { ...anchor, direction: "older" }
      : {
          kind: "anchor",
          messageIndex: -1,
          scrollTop: scrollRef.current?.scrollTop ?? 0,
          screenY: 0,
          direction: "older",
        };
    setWindowState({ resetKey, range: next });
    return true;
  }, [messages.length, mountBudget, onHistoryNavigation, pageSize, range, resetKey, scrollRef]);

  const loadNewer = useCallback(() => {
    const next = newerTranscriptRange(range, messages.length, mountBudget, pageSize);
    const reachesTail = next.end >= messages.length;
    onHistoryNavigation?.(reachesTail);
    if (!sameTranscriptRange(range, next)) {
      if (reachesTail) {
        pendingViewportRef.current = { kind: "bottom" };
      } else {
        const anchor = captureViewportAnchor(scrollRef);
        pendingViewportRef.current = anchor
          ? { ...anchor, direction: "newer" }
          : {
              kind: "anchor",
              messageIndex: -1,
              scrollTop: scrollRef.current?.scrollTop ?? 0,
              screenY: 0,
              direction: "newer",
            };
      }
      setWindowState({ resetKey, range: next });
    }
    return reachesTail;
  }, [messages.length, mountBudget, onHistoryNavigation, pageSize, range, resetKey, scrollRef]);

  const resetToTail = useCallback(() => {
    pendingViewportRef.current = { kind: "bottom" };
    setWindowState({ resetKey, range: tailTranscriptRange(messages.length, mountBudget) });
  }, [messages.length, mountBudget, resetKey]);

  if (controlsRef) {
    controlsRef.current = {
      loadOlder,
      loadNewer,
      resetToTail,
      getRange: () => range,
    };
  }

  useEffect(() => () => {
    if (viewportTimerRef.current) clearTimeout(viewportTimerRef.current);
    if (controlsRef) controlsRef.current = null;
  }, [controlsRef]);

  useEffect(() => {
    if (!followingTail) return;
    const tail = tailTranscriptRange(messages.length, mountBudget);
    setWindowState((current) => {
      const currentRange = current.resetKey === resetKey ? current.range : range;
      if (current.resetKey === resetKey && sameTranscriptRange(currentRange, tail)) return current;
      return { resetKey, range: tail };
    });
  }, [followingTail, messages.length, mountBudget, range, resetKey]);

  useEffect(() => {
    const box = scrollRef.current;
    if (windowState.resetKey !== resetKey) {
      pendingViewportRef.current = null;
      setWindowState({ resetKey, range: tailTranscriptRange(messages.length, mountBudget) });
      if (box) scheduleViewportCorrection(() => {
        const currentBox = scrollRef.current;
        if (currentBox) scrollToBottom(currentBox);
      });
      return;
    }

    const pending = pendingViewportRef.current;
    if (!pending) return;
    pendingViewportRef.current = null;
    if (!box) return;
    scheduleViewportCorrection(() => {
      const currentBox = scrollRef.current;
      if (!currentBox) return;
      if (pending.kind === "bottom") {
        scrollToBottom(currentBox);
        return;
      }

      const anchor = pending.messageIndex >= 0
        ? currentBox.content.getChildren().find(
            (child) => child.id === `${MESSAGE_RENDERABLE_PREFIX}${pending.messageIndex}`,
          )
        : undefined;
      if (anchor) {
        currentBox.scrollTop = Math.max(
          0,
          pending.scrollTop + anchor.screenY - pending.screenY,
        );
      } else if (pending.direction === "older") {
        // The previous viewport was beyond the overlap and has slid out of the
        // bounded page. Show the newest part of this older page, not transcript tail.
        currentBox.scrollTop = Math.max(0, currentBox.scrollHeight - currentBox.viewport.height);
      } else {
        currentBox.scrollTop = 0;
      }
    });
  }, [mountBudget, messages.length, range.end, range.start, resetKey, scheduleViewportCorrection, scrollRef, windowState.resetKey]);

  const olderCount = range.start;
  const newerCount = Math.max(0, messages.length - range.end);

  return (
    <>
      {olderCount > 0 ? (
        <box
          id="transcript-window-older"
          style={{ width: "100%", height: 1, flexShrink: 0, paddingLeft: 1 }}
          onMouseDown={() => {
            loadOlder();
          }}
        >
          <text selectable={false}>
            {`↑ 查看更早消息 · PgUp（还有 ${olderCount} 条）`}
          </text>
        </box>
      ) : null}
      {messages.slice(range.start, range.end).map((message, offset) => {
        const index = range.start + offset;
        return (
          <box
            key={message.id}
            id={`${MESSAGE_RENDERABLE_PREFIX}${index}`}
            style={{ width: "100%", paddingTop: 1 }}
          >
            {renderMessage(message, index)}
          </box>
        );
      })}
      {newerCount > 0 ? (
        <box
          id="transcript-window-newer"
          style={{ width: "100%", height: 1, flexShrink: 0, paddingLeft: 1 }}
          onMouseDown={() => {
            loadNewer();
          }}
        >
          <text selectable={false}>
            {`↓ 查看较新消息 · PgDn（还有 ${newerCount} 条）`}
          </text>
        </box>
      ) : null}
    </>
  );
}
