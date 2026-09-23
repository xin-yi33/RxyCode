import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

describe("OpenTUI busy follow-up queue", () => {
  const src = readFileSync(
    path.join(path.dirname(fileURLToPath(import.meta.url)), "App.tsx"),
    "utf8",
  );
  const bar = readFileSync(
    path.join(path.dirname(fileURLToPath(import.meta.url)), "FollowupQueueBar.tsx"),
    "utf8",
  );

  test("composer stays focused and queues chat while streaming", () => {
    expect(src).toContain("focused={!dialogOpen}");
    expect(src).not.toContain("focused={!isStreaming && !dialogOpen}");
    expect(src).toContain("enqueueBusyFollowup");
    expect(src).toContain("takeNextFollowup");
    expect(src).not.toMatch(/if \(isStreaming\) return;/);
  });

  test("queue rows expose send now, edit, and delete", () => {
    expect(src).toContain("FollowupQueueBar");
    expect(src).toContain("handleQueueSendNow");
    expect(src).toContain("handleQueueEdit");
    expect(src).toContain("handleQueueDelete");
    expect(src).toContain("takeFollowupById");
    expect(src).toContain("steerTurn");
    expect(src).not.toContain("已立即发送到当前回合");
  });

  test("queue bar labels match send now / edit / delete", () => {
    expect(bar).toContain("[立即发送]");
    expect(bar).toContain("[编辑]");
    expect(bar).toContain("[删除]");
    expect(bar).toContain("onSendNow");
    expect(bar).toContain("onEdit");
    expect(bar).toContain("onDelete");
  });
});
