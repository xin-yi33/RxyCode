import { describe, expect, test } from "bun:test";
import { useState } from "react";
import { testRender } from "@opentui/react/test-utils";
import { DialogDoc } from "./DialogDoc.tsx";

function longBody(count: number): string {
  return Array.from({ length: count }, (_, i) => `LINE-${String(i).padStart(2, "0")}`).join("\n");
}

function Fixture() {
  const [closed, setClosed] = useState(false);
  if (closed) return <text>closed</text>;
  return (
    <DialogDoc
      kind="help"
      body={longBody(40)}
      onClose={() => setClosed(true)}
    />
  );
}

describe("DialogDoc keyboard (headless mockInput)", () => {
  test("arrow down reveals later help lines", async () => {
    const { mockInput, flush, captureCharFrame, renderer } = await testRender(
      <Fixture />,
      { width: 80, height: 22 },
    );
    try {
      await flush();
      const before = captureCharFrame();
      expect(before).toContain("LINE-00");
      expect(before).toMatch(/1-\d+\/40/);

      for (let i = 0; i < 12; i++) {
        mockInput.pressArrow("down");
      }
      await flush();
      const after = captureCharFrame();
      expect(after).toMatch(/1[3-9]-\d+\/40|2\d-\d+\/40/);
    } finally {
      renderer.destroy();
    }
  });
});
