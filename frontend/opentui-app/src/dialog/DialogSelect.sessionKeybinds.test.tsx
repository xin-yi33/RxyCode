/**
 * Optional onKeybind must not change default DialogSelect esc close.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { DialogSelect, type DialogSelectOption } from "./DialogSelect.tsx";

const OPTIONS: DialogSelectOption<string>[] = [
  { id: "a", title: "alpha", category: "会话", value: "a" },
  { id: "b", title: "beta", category: "会话", value: "b" },
];

describe("DialogSelect session keybinds optional", () => {
  test("without onKeybind, dialog still renders and escape stays first", async () => {
    const { flush, captureCharFrame, renderer } = await testRender(
      <DialogSelect
        title="会话"
        options={OPTIONS}
        placeholder="搜索"
        onClose={() => undefined}
        onSelect={() => undefined}
      />,
      { width: 80, height: 24 },
    );
    try {
      await flush();
      expect(captureCharFrame()).toContain("会话");
    } finally {
      renderer.destroy();
    }

    const body = readFileSync(resolve(__dirname, "DialogSelect.tsx"), "utf8");
    const escIdx = body.indexOf('if (key.name === "escape")');
    const bindIdx = body.indexOf("if (onKeybind)");
    expect(escIdx).toBeGreaterThan(0);
    expect(bindIdx).toBeGreaterThan(escIdx);
    expect(body.slice(escIdx, escIdx + 160)).toContain("onClose()");
    expect(body).toContain("onKeybind?:");
  });
});
