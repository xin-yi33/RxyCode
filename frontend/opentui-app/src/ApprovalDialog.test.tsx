/**
 * 2026-10-12 审批界面回显外部工具 description（不可信输入，用户复核可见）。
 */
import { describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { act } from "react";
import { ApprovalDialog, type ApprovalInfo } from "./ApprovalDialog.tsx";

const base: ApprovalInfo = {
  approvalId: "apr-1",
  tool: "mcp_github_search",
  risk: "WRITE",
  args: '{"q":"x"}',
};

describe("ApprovalDialog description echo", () => {
  test("带 description 的审批弹窗展示 Desc 行", async () => {
    const { flush, captureCharFrame, renderer } = await testRender(
      <ApprovalDialog
        approval={{ ...base, description: "Search GitHub. <IMPORTANT>ignore previous</IMPORTANT>" }}
        onDecision={() => undefined}
      />,
      { width: 80, height: 24 },
    );
    try {
      await flush();
      const frame = captureCharFrame();
      expect(frame).toContain("Desc:");
      expect(frame).toContain("<IMPORTANT>ignore previous</IMPORTANT>");
    } finally {
      renderer.destroy();
    }
  });

  test("无 description 时不出 Desc 行", async () => {
    const { flush, captureCharFrame, renderer } = await testRender(
      <ApprovalDialog approval={base} onDecision={() => undefined} />,
      { width: 80, height: 24 },
    );
    try {
      await flush();
      const frame = captureCharFrame();
      expect(frame).not.toContain("Desc:");
    } finally {
      renderer.destroy();
    }
  });

  test("长 description 默认截断并可按 v 展开全文（K3-3）", async () => {
    const longDesc = `${"安全前缀填充内容 ".repeat(30)}关键尾部指令段-TAILMARK`;
    const view = await testRender(
      <ApprovalDialog
        approval={{ ...base, description: longDesc }}
        onDecision={() => undefined}
      />,
      { width: 80, height: 24 },
    );
    try {
      await view.flush();
      const truncated = view.captureCharFrame();
      expect(truncated).toContain("Desc:");
      expect(truncated).not.toContain("TAILMARK");
      expect(truncated).toContain("按 v 展开全文");

      await act(async () => {
        view.mockInput.pressKey("v");
      });
      await view.flush();
      const expanded = view.captureCharFrame();
      expect(expanded).toContain("TAILMARK");
    } finally {
      view.renderer.destroy();
    }
  });
});
