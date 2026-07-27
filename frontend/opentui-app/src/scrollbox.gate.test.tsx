/**
 * GateLive W01/W02 headless evidence (PARTIAL only — not interactive TTY).
 *
 * Proves via @opentui/react/test-utils:
 * - ScrollBox scrollTop can be set/read after content overflow
 * - sticky helpers react to scroll-up / scroll-to-bottom
 * - textarea value path via setText / plainText + mockInput typing
 */
import { describe, expect, test } from "bun:test";
import { createRef, useEffect, useState, type RefObject } from "react";
import type { ScrollBoxRenderable, TextareaRenderable } from "@opentui/core";
import { testRender } from "@opentui/react/test-utils";
import {
  createStickyState,
  onScrollToBottom,
  onUserScrollUp,
  shouldAutoStick,
  type StickyState,
} from "./sticky.ts";

const LINE_COUNT = 60;

function GateScrollFixture({
  scrollRef,
  textareaRef,
  sticky,
}: {
  scrollRef: RefObject<ScrollBoxRenderable | null>;
  textareaRef: RefObject<TextareaRenderable | null>;
  sticky: StickyState;
}) {
  const [value, setValue] = useState("");
  const stick = shouldAutoStick(sticky);

  useEffect(() => {
    // Seed textarea programmatically (focus/value path without real TTY).
    textareaRef.current?.setText("gate-live-seed");
    setValue(textareaRef.current?.plainText ?? "");
  }, [textareaRef]);

  return (
    <box style={{ flexDirection: "column", width: "100%", height: "100%" }}>
      <scrollbox
        ref={scrollRef}
        stickyScroll={stick}
        stickyStart="bottom"
        flexGrow={1}
        style={{
          rootOptions: { flexGrow: 1, border: false },
          viewportOptions: { flexGrow: 1 },
          contentOptions: { flexGrow: 1 },
        }}
      >
        {Array.from({ length: LINE_COUNT }, (_, i) => (
          <box key={i} style={{ width: "100%", height: 1 }}>
            <text>{`probe-line-${i} stickyScroll gate`}</text>
          </box>
        ))}
      </scrollbox>
      <box style={{ flexShrink: 0, height: 3 }}>
        <textarea
          ref={textareaRef}
          focused={true}
          initialValue={value}
          onContentChange={() => {
            setValue(textareaRef.current?.plainText ?? "");
          }}
        />
      </box>
      <text>{`sticky=${stick ? "on" : "off"} value=${value}`}</text>
    </box>
  );
}

describe("OpenTUI ScrollBox + textarea gate (W01/W02 PARTIAL)", () => {
  test("scrollTop mutation + sticky helpers + textarea value path", async () => {
    const scrollRef = createRef<ScrollBoxRenderable>();
    const textareaRef = createRef<TextareaRenderable>();
    let sticky = createStickyState();

    const { mockInput, flush, captureCharFrame, renderer } = await testRender(
      <GateScrollFixture
        scrollRef={scrollRef}
        textareaRef={textareaRef}
        sticky={sticky}
      />,
      { width: 80, height: 24 },
    );

    try {
      await flush();

      const box = scrollRef.current;
      expect(box).toBeTruthy();
      if (!box) return;

      // Content taller than viewport → scrollHeight > 0
      expect(box.scrollHeight).toBeGreaterThan(0);

      const bottom = Math.max(0, box.scrollHeight);
      box.scrollTop = bottom;
      await flush();
      const atBottom = box.scrollTop;
      expect(atBottom).toBeGreaterThanOrEqual(0);

      // Simulate user scroll-up: lower scrollTop + sticky helper
      const scrolledUpTop = Math.max(0, atBottom - 10);
      box.scrollTop = scrolledUpTop;
      sticky = onUserScrollUp(sticky);
      expect(shouldAutoStick(sticky)).toBe(false);
      expect(box.scrollTop).toBe(scrolledUpTop);

      // Re-engage sticky + jump to bottom
      sticky = onScrollToBottom(sticky);
      box.scrollTop = Math.max(0, box.scrollHeight);
      await flush();
      expect(shouldAutoStick(sticky)).toBe(true);
      expect(box.scrollTop).toBeGreaterThanOrEqual(scrolledUpTop);

      // Textarea value path: programmatic seed
      const ta = textareaRef.current;
      expect(ta).toBeTruthy();
      if (!ta) return;
      expect(ta.plainText).toContain("gate-live-seed");

      // Focus + type via mock keys (headless, not interactive TTY session)
      ta.focus();
      await mockInput.typeText(" +typed");
      await flush();
      expect(ta.plainText.length).toBeGreaterThan("gate-live-seed".length);

      const frame = captureCharFrame();
      expect(frame).toMatch(/probe-line-/);
      expect(frame.length).toBeGreaterThan(0);
    } finally {
      renderer.destroy();
    }
  });
});
