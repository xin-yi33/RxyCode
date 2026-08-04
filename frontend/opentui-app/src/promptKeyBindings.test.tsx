import { describe, expect, test } from "bun:test";
import { createRef } from "react";
import type { TextareaRenderable } from "@opentui/core";
import { testRender } from "@opentui/react/test-utils";
import { CHAT_PROMPT_KEY_BINDINGS } from "./promptKeyBindings.ts";

function PromptFixture({ onSubmit }: { onSubmit: (text: string) => void }) {
  const ref = createRef<TextareaRenderable>();

  return (
    <textarea
      ref={ref}
      focused
      keyBindings={CHAT_PROMPT_KEY_BINDINGS}
      onSubmit={() => {
        onSubmit(ref.current?.plainText ?? "");
      }}
    />
  );
}

describe("CHAT_PROMPT_KEY_BINDINGS", () => {
  test("maps Enter to submit and Shift+Enter to newline", () => {
    expect(CHAT_PROMPT_KEY_BINDINGS).toContainEqual({ name: "return", action: "submit" });
    expect(CHAT_PROMPT_KEY_BINDINGS).toContainEqual({
      name: "return",
      shift: true,
      action: "newline",
    });
  });

  test("Enter submits /model instead of inserting newline", async () => {
    let submitted = "";
    const { mockInput, flush, renderer } = await testRender(
      <PromptFixture
        onSubmit={(text) => {
          submitted = text;
        }}
      />,
      { width: 80, height: 12 },
    );

    try {
      await flush();
      await mockInput.typeText("/model");
      await flush();
      mockInput.pressEnter();
      await flush();
      expect(submitted).toBe("/model");
    } finally {
      renderer.destroy();
    }
  });
});
