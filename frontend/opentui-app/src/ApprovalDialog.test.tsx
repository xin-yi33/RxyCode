/**
 * 2026-10-12 审批界面回显外部工具 description（不可信输入，用户复核可见）。
 */
import { describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
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
});
