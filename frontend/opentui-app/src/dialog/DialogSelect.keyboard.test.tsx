/**
 * Headless DialogSelect keyboard path (mockInput — not Windows ConPTY).
 * Proves filter + Enter select /model (nested-dialog routing prerequisite).
 */
import { describe, expect, test } from "bun:test";
import { useState } from "react";
import { testRender } from "@opentui/react/test-utils";
import { DialogSelect, type DialogSelectOption } from "./DialogSelect.tsx";
import type { Command } from "../commands.ts";

const OPTIONS: DialogSelectOption<Command>[] = [
  {
    id: "/clear",
    title: "/clear",
    description: "清除",
    category: "会话",
    value: { name: "/clear", description: "清除", category: "会话", action: "clear", local: true },
  },
  {
    id: "/addmodel",
    title: "/addmodel",
    description: "添加",
    category: "Agent",
    value: { name: "/addmodel", description: "添加", category: "Agent", action: "addmodel", local: false },
  },
  {
    id: "/model",
    title: "/model",
    description: "切换",
    category: "Agent",
    value: { name: "/model", description: "切换", category: "Agent", action: "model", local: false },
  },
  {
    id: "/models",
    title: "/models",
    description: "列表",
    category: "Agent",
    value: { name: "/models", description: "列表", category: "Agent", action: "models", local: false },
  },
];

function Fixture({ onSelect }: { onSelect: (id: string) => void }) {
  const [closed, setClosed] = useState(false);
  if (closed) return <text>closed</text>;
  return (
    <DialogSelect
      title="命令"
      options={OPTIONS}
      categoryOrder={["会话", "Agent"]}
      placeholder="搜索"
      onClose={() => setClosed(true)}
      onSelect={(opt) => onSelect(opt.id)}
    />
  );
}

describe("DialogSelect keyboard (headless mockInput)", () => {
  test("type model + Enter selects /model", async () => {
    let selected = "";
    const { mockInput, flush, captureCharFrame, renderer } = await testRender(
      <Fixture
        onSelect={(id) => {
          selected = id;
        }}
      />,
      { width: 80, height: 28 },
    );
    try {
      await flush();
      const before = captureCharFrame();
      expect(before).toContain("命令");
      expect(before).toContain("/clear");

      await mockInput.typeText("model");
      await flush();
      const filtered = captureCharFrame();
      expect(filtered).toMatch(/model/i);
      expect(filtered).toContain("/model");

      mockInput.pressEnter();
      await flush();
      expect(selected).toBe("/model");
    } finally {
      renderer.destroy();
    }
  });

  test("paste model then Enter selects /model", async () => {
    let selected = "";
    const { mockInput, flush, captureCharFrame, renderer } = await testRender(
      <Fixture
        onSelect={(id) => {
          selected = id;
        }}
      />,
      { width: 80, height: 28 },
    );
    try {
      await flush();
      await mockInput.pasteBracketedText("model");
      await flush();
      const filtered = captureCharFrame();
      expect(filtered).toContain("/model");
      mockInput.pressEnter();
      await flush();
      expect(selected).toBe("/model");
    } finally {
      renderer.destroy();
    }
  });
});
