import { describe, expect, test } from "bun:test";
import { useState } from "react";
import { testRender } from "@opentui/react/test-utils";
import { act } from "react";
import { DialogSelect, type DialogSelectOption } from "./DialogSelect.tsx";

const OPTIONS: DialogSelectOption<string>[] = [
  { id: "deepseek-chat", title: "deepseek-chat", category: "可用模型", value: "deepseek-chat" },
  { id: "deepseek-reasoner", title: "deepseek-reasoner", category: "可用模型", value: "deepseek-reasoner" },
];

function MultiFixture({
  onConfirm,
}: {
  onConfirm: (ids: string[], meta: { highlightedId: string }) => void;
}) {
  const [closed, setClosed] = useState(false);
  if (closed) return <text>closed</text>;
  return (
    <DialogSelect
      title="选择模型"
      options={OPTIONS}
      multi
      defaultSelectedIds={OPTIONS.map((o) => o.id)}
      onClose={() => setClosed(true)}
      onConfirm={onConfirm}
    />
  );
}

describe("DialogSelect multi (headless mockInput)", () => {
  test("default selects all models with checkmarks", async () => {
    const { flush, captureCharFrame, renderer } = await testRender(
      <MultiFixture onConfirm={() => {}} />,
      { width: 80, height: 28 },
    );
    try {
      await flush();
      const frame = captureCharFrame();
      expect(frame).toContain("deepseek-chat");
      expect(frame).toContain("deepseek-reason");
      expect(frame.match(/✓/g)?.length).toBe(2);
    } finally {
      renderer.destroy();
    }
  });

  test("space toggles selection and Enter confirms without onSelect", async () => {
    let confirmed: { ids: string[]; highlightedId: string } | null = null;
    let selectedSingle = "";
    const { mockInput, flush, renderer } = await testRender(
      <DialogSelect
        title="选择模型"
        options={OPTIONS}
        multi
        showSearch={false}
        defaultSelectedIds={OPTIONS.map((o) => o.id)}
        onClose={() => {}}
        onSelect={(opt) => {
          selectedSingle = opt.id;
        }}
        onConfirm={(ids, meta) => {
          confirmed = { ids, highlightedId: meta.highlightedId };
        }}
      />,
      { width: 80, height: 28 },
    );
    try {
      await flush();
      await act(async () => {
        mockInput.pressKey(" ");
      });
      await flush();
      await act(async () => {
        mockInput.pressEnter();
      });
      await flush();
      expect(selectedSingle).toBe("");
      expect(confirmed).not.toBeNull();
      expect(confirmed!.ids).toContain("deepseek-reasoner");
      expect(confirmed!.ids).not.toContain("deepseek-chat");
      expect(confirmed!.highlightedId).toBe("deepseek-chat");
    } finally {
      renderer.destroy();
    }
  });
});
