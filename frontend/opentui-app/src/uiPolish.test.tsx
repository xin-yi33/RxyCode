/**
 * UI polish contract for the OpenTUI shell (task UI-07).
 *
 * Locks three things the user can see:
 *  1. base surfaces are a near-black token family, never pure #000;
 *  2. numeric fields (durations, sizes, counts, quota) sit on display-cell
 *     columns so CJK labels and growing values do not shift the layout;
 *  3. copy feedback is one 2500ms window and a failed copy never says "Copied";
 *  4. long file names keep their (compound) suffix via a middle ellipsis;
 *  5. no CSS blur / spring / per-character reveal timers leak into the TUI.
 *
 * Component behaviour is asserted with @opentui/react/test-utils on the real
 * App / ToolCard / DialogSelect render paths, not re-implemented fixtures.
 */
import { afterEach, describe, expect, mock, test } from "bun:test";
import { readFileSync } from "node:fs";
import { testRender } from "@opentui/react/test-utils";
import { act, useEffect } from "react";

process.env.RXYCODE_TRANSPORT = "http";
process.env.RXYCODE_API_URL = "http://127.0.0.1:9";
process.env.RXYCODE_API_TOKEN = "synthetic-test-token";

const axiosGet = mock(async (url: string) => ({
  data: url.endsWith("/status")
    ? {
        model: "polish-model",
        mode: "build",
        context_used_k: 1,
        context_max_k: 64,
        cache_size: "0B",
        cache_rate: "0.0%",
        capabilities: { prompt_attachments: true },
      }
    : { models: [{ id: "polish-model", name: "polish-model" }] },
}));
mock.module("axios", () => ({
  default: {
    get: axiosGet,
    post: mock(async () => ({ data: { ok: true } })),
    isAxiosError: () => false,
  },
}));

import {
  C,
  SURFACES,
  SURFACE_KEYS,
  isPureBlack,
  relativeLuminance,
} from "./theme.ts";
import {
  alignSignedCounts,
  alignEdges,
  displayWidth,
  durationCell,
  formatBytesCompact,
  formatCountSummary,
  formatDurationCompact,
  formatQuotaPair,
  padDisplayEnd,
  padDisplayStart,
  sizeCell,
  DURATION_COLUMN_WIDTH,
} from "./lib/displayColumns.ts";
import {
  COMPOUND_SUFFIXES,
  middleEllipsisFileName,
  splitCompoundSuffix,
  splitFileNameForWidth,
} from "./lib/fileName.ts";
import { COPY_FEEDBACK_MS, copyFeedbackLabel, useCopyFeedback } from "./lib/copyFeedback.ts";
import { buildStatusSegments, formatStatusBarText } from "./statusBar.ts";
import { todoDockLines } from "./todoDock.ts";
import { ToolCard } from "./ToolCard.tsx";
import type { ChatMessage } from "./types.ts";
import { DialogSelect } from "./dialog/DialogSelect.tsx";
import type { ChatTransport } from "./transport/types.ts";
import type { ClipboardAttachment, ClipboardCaptureResult } from "./clipboard.ts";

const READ = (relative: string): string =>
  readFileSync(new URL(relative, import.meta.url), "utf8");

const { __setChatTransportForTests, resetChatTransportForTests } = await import("./transport/index.ts");
const { __setClipboardCaptureForTests } = await import("./clipboard.ts");
const { DialogProvider } = await import("./dialog/DialogHost.tsx");
const { default: App } = await import("./App.tsx");

function makeTransport(
  sendChatMessage: ChatTransport["sendChatMessage"] = async () => {},
): ChatTransport {
  return {
    kind: "http",
    getCurrentSessionId: () => "ui-polish-session",
    fetchStatus: async (onStatus) => {
      onStatus({
        model: "polish-model",
        mode: "build",
        context_used_k: 1,
        context_max_k: 64,
        cache_size: "0B",
        cache_rate: "0.0%",
        capabilities: { prompt_attachments: true },
      });
    },
    sendCommand: async () => ({ ok: true, permission_mode: "auto_edit" }),
    cancelActiveRequest: async () => {},
    steerTurn: async () => ({ ok: true }),
    respondApproval: async () => true,
    respondQuestion: async () => true,
    sendChatMessage,
    invokeSubagent: async () => {
      throw new Error("not used");
    },
    listChildSessions: async () => [],
    openChildSession: async () => ({ ok: false, message: "not used" }),
    openParentSession: async () => ({ ok: false, message: "not used" }),
    listSessions: async () => [],
    attachSession: async () => ({ session_id: "ui-polish-session", messages: [] }),
    renameSession: async () => ({ session_id: "ui-polish-session" }),
    trashSession: async () => {},
    pinSession: async () => {},
    forkSession: async () => ({ session_id: "ui-polish-fork" }),
  };
}

async function settle(ui: { flush: () => Promise<void> }, delayMs = 20): Promise<void> {
  await act(async () => {
    await ui.flush();
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    await ui.flush();
  });
}

afterEach(() => {
  __setClipboardCaptureForTests(null);
  resetChatTransportForTests();
});

describe("base surfaces: near-black tokens, never pure #000", () => {
  test("every surface token is a near-black that is not #000", () => {
    expect(SURFACE_KEYS.length).toBeGreaterThanOrEqual(5);
    for (const key of SURFACE_KEYS) {
      const value = SURFACES[key];
      expect(value).toMatch(/^#[0-9a-f]{6}$/);
      expect(isPureBlack(value)).toBe(false);
      // Near-black: each channel is tiny but not all zero.
      const channels = value.slice(1).match(/.{2}/g)!.map((hex) => Number.parseInt(hex, 16));
      expect(Math.max(...channels)).toBeLessThanOrEqual(0x40);
      expect(Math.max(...channels)).toBeGreaterThan(0);
    }
  });

  test("surface hierarchy is ordered by luminance (app < field < panels < raised)", () => {
    const app = relativeLuminance(SURFACES.app);
    const field = relativeLuminance(SURFACES.field);
    const panel = relativeLuminance(SURFACES.surface0);
    const bubble = relativeLuminance(SURFACES.userBubble);
    const raised = relativeLuminance(SURFACES.surface1);
    expect(field).toBeGreaterThan(app);
    expect(panel).toBeGreaterThan(field);
    expect(bubble).toBeGreaterThan(panel);
    expect(raised).toBeGreaterThan(bubble);
  });

  test("C re-exports the surface tokens for the real render path", () => {
    expect(C.bg).toBe(SURFACES.app);
    expect(C.field).toBe(SURFACES.field);
    expect(C.panel).toBe(SURFACES.surface0);
    expect(C.surface0).toBe(SURFACES.surface0);
    expect(C.userBubble).toBe(SURFACES.userBubble);
    expect(isPureBlack(C.bg)).toBe(false);
  });

  test("brand logo field uses the canvas token instead of #000000", async () => {
    const brand = await import("./brand.ts");
    expect(brand.LOGO_FIELD_BG).toBe(SURFACES.app);
    expect(brand.LOGO_FIELD_BG).not.toBe("#000000");
  });

  test("App / dialogs paint backgrounds from tokens, not literal #000", () => {
    const app = READ("./App.tsx");
    expect(app).toContain("backgroundColor: C.bg");
    expect(app).toContain("backgroundColor: C.field");
    expect(app).not.toMatch(/backgroundColor:\s*"#000000"/);
    expect(app).not.toContain("LOGO_FIELD_BG = \"#000000\"");
    for (const dialog of [
      "./dialog/DialogSelect.tsx",
      "./dialog/DialogConfirm.tsx",
      "./dialog/DialogDoc.tsx",
      "./dialog/DialogPrompt.tsx",
      "./dialog/DialogMCP.tsx".replace("MCP", "Mcp"),
      "./dialog/DialogStatus.tsx",
      "./dialog/DialogMemory.tsx",
      "./dialog/DialogSkills.tsx",
      "./Modal.tsx",
      "./ApprovalDialog.tsx",
      "./QuestionDialog.tsx",
      "./PlanPane.tsx",
    ]) {
      const source = READ(dialog);
      // Dialogs/cards use the panel token (PlanPane predates the alias and
      // already used C.surface0 — both are the same value).
      expect(source).toMatch(/backgroundColor: C\.(panel|surface0)/);
      expect(source).not.toMatch(/backgroundColor:\s*"#000000"/);
    }
  });
});

describe("numeric columns: display-cell alignment", () => {
  test("pad helpers use display width, not JS length (CJK is 2 cells)", () => {
    expect(displayWidth("中文")).toBe(4);
    expect(padDisplayStart("1", 4)).toBe("   1");
    expect(padDisplayEnd("中文", 6)).toBe("中文  ");
    expect(padDisplayEnd("中文", 4)).toBe("中文");
    expect(displayWidth(padDisplayStart("中文", 8))).toBe(8);
  });

  test("durations render in a fixed-width cell", () => {
    expect(formatDurationCompact(0)).toBe("0.0s");
    expect(formatDurationCompact(500)).toBe("0.5s");
    expect(formatDurationCompact(65_000)).toBe("1m05s");
    expect(formatDurationCompact(3_930_000)).toBe("1h05m");
    for (const ms of [0, 999, 59_900, 60_000, 3_930_000, 36_000_000]) {
      expect(displayWidth(durationCell(ms))).toBe(DURATION_COLUMN_WIDTH);
    }
    expect(durationCell(500)).toBe("  0.5s");
  });

  test("file sizes are compact and right-aligned in their column", () => {
    expect(formatBytesCompact(0)).toBe("0B");
    expect(formatBytesCompact(12 * 1024)).toBe("12.0KB");
    expect(formatBytesCompact(907 * 1024)).toBe("907KB");
    expect(formatBytesCompact(1.5 * 1024 * 1024)).toBe("1.5MB");
    expect(sizeCell("0B")).toBe("    0B");
    expect(displayWidth(sizeCell("907.0k"))).toBe(6);
  });

  test("quota pairs keep the slash column fixed across growing values", () => {
    const small = formatQuotaPair("1.2k", "256k");
    const large = formatQuotaPair("41.1k", "1049k");
    expect(small).toBe(" 1.2k/ 256k");
    expect(small.indexOf("/")).toBe(large.indexOf("/").valueOf() >= 0 ? small.indexOf("/") : -1);
    expect(displayWidth(small)).toBe(displayWidth(large));
    expect(small.indexOf("/")).toBe(large.indexOf("/"));
  });

  test("count columns align, and the legacy 1/1 summary text is unchanged", () => {
    expect(formatCountSummary([{ count: 1, label: "completed" }, { count: 1, label: "cancelled" }]))
      .toBe("1 completed, 1 cancelled");
    const wide = formatCountSummary([
      { count: 12, label: "completed" },
      { count: 1, label: "cancelled" },
    ]);
    expect(wide).toBe("12 completed,  1 cancelled");
    // Only the numeric cells share a column; "completed"/"cancelled" differ.
    expect(wide.startsWith("12 completed")).toBe(true);
    expect(wide.includes(",  1 cancelled")).toBe(true);
  });

  test("signed diff counts put the digits on one grid column", () => {
    expect(alignSignedCounts(3, 12)).toEqual({ added: "+ 3", removed: "-12" });
    expect(displayWidth(alignSignedCounts(3, 12).added)).toBe(
      displayWidth(alignSignedCounts(3, 12).removed),
    );
  });

  test("status bar renders aligned quota / size / rate cells", () => {
    const segments = buildStatusSegments({
      connected: true,
      contextUsedK: 1.2,
      contextMaxK: 256,
      cacheSize: "12KB",
      cacheRate: "33.0%",
      mode: "build",
      thinkingExpanded: false,
      width: 160,
      modeColor: "#FF69B4",
    });
    const context = segments.find((segment) => segment.key === "context")!;
    const cache = segments.find((segment) => segment.key === "cache")!;
    expect(context.text).toBe("上下文: 1.2k/ 256k");
    expect(cache.text).toBe("缓存:  12KB/33.0%");

    // The slash and the right edge stay put while the used count grows.
    const bigger = buildStatusSegments({
      connected: true,
      contextUsedK: 41.1,
      contextMaxK: 256,
      cacheSize: "907.0k",
      cacheRate: "96.2%",
      mode: "build",
      thinkingExpanded: false,
      width: 160,
      modeColor: "#FF69B4",
    });
    const biggerContext = bigger.find((segment) => segment.key === "context")!;
    const biggerCache = bigger.find((segment) => segment.key === "cache")!;
    expect(displayWidth(biggerContext.text)).toBe(displayWidth(context.text));
    expect(biggerContext.text.indexOf("/")).toBe(context.text.indexOf("/"));
    expect(displayWidth(biggerCache.text)).toBe(displayWidth(cache.text));
    expect(biggerCache.text.indexOf("/")).toBe(cache.text.indexOf("/"));
    expect(formatStatusBarText({
      connected: true,
      contextUsedK: 1.2,
      contextMaxK: 256,
      cacheSize: "12KB",
      cacheRate: "33.0%",
      mode: "build",
      thinkingExpanded: false,
      width: 160,
      modeColor: "#FF69B4",
    })).toContain(context.text);
  });

  test("todo dock count summary uses aligned count cells", () => {
    const lines = todoDockLines({
      list_id: "default",
      revision: 2,
      items: [
        { id: "t1", content: "a", status: "pending" },
        { id: "t2", content: "b", status: "completed" },
      ],
    });
    // One open task keeps the per-item rows plus the supplementary summary.
    expect(lines.at(-1)).toBe("(1 completed)");
    const many = Array.from({ length: 12 }, (_, index) => ({
      id: `t${index}`,
      content: "done",
      status: "completed",
    }));
    const wideLines = todoDockLines({
      list_id: "default",
      revision: 3,
      items: [...many, { id: "open", content: "still open", status: "pending" }],
    });
    expect(wideLines.at(-1)).toBe("(12 completed)");
  });

  test("ToolCard renders name/status/duration on fixed display columns", async () => {
    const now = Date.now();
    const message = (id: string, name: string, startedAt: number, endedAt: number): ChatMessage => ({
      id,
      role: "tool",
      content: "ok",
      timestamp: startedAt,
      toolName: name,
      toolStatus: "success",
      toolArgs: name === "bash" ? '{"command":"echo hi"}' : "file.ts",
      toolExpanded: true,
      endedAt,
    });
    const ctrlHeldRef = { current: false };
    const ui = await testRender(
      <box style={{ flexDirection: "column", width: "100%" }}>
        <ToolCard msg={message("t1", "bash", now - 500, now)} wrapW={70} ctrlHeldRef={ctrlHeldRef} onChanged={() => {}} />
        <ToolCard msg={message("t2", "read", now - 65_000, now)} wrapW={70} ctrlHeldRef={ctrlHeldRef} onChanged={() => {}} />
      </box>,
      { width: 80, height: 8 },
    );
    try {
      await ui.flush();
      const frame = ui.captureCharFrame();
      const lines = frame.split("\n").filter((line) => line.includes(">_"));
      expect(lines.length).toBe(2);
      const [first, second] = lines;
      // Fixed name (10) + status (11) cells: the status column starts at the
      // same display column, and the duration/toggle columns follow it.
      const bracket = (line: string) => line.indexOf("[success]");
      expect(bracket(first!)).toBe(bracket(second!));
      expect(displayWidth(first!.slice(0, bracket(first!)))).toBe(
        displayWidth(second!.slice(0, bracket(second!))),
      );
      expect(first!.indexOf("0.5s")).toBeGreaterThan(0);
      expect(second!.indexOf("1m05s")).toBeGreaterThan(0);
      // Duration cells are both six cells wide and end on the same column.
      expect(first!.indexOf("0.5s") + displayWidth("0.5s")).toBe(
        second!.indexOf("1m05s") + displayWidth("1m05s"),
      );
    } finally {
      ui.renderer.destroy();
    }
  });
});

describe("copy feedback: one 2500ms window, honest result", () => {
  test("shared window constant and labels", () => {
    expect(COPY_FEEDBACK_MS).toBe(2500);
    expect(copyFeedbackLabel(true)).toContain("Copied to clipboard");
    expect(copyFeedbackLabel(false)).not.toContain("Copied");
    expect(copyFeedbackLabel(false)).toContain("复制失败");
  });

  test("hook shows the chip then reverts after the window", async () => {
    function Harness({ delay }: { delay: number }) {
      const controller = useCopyFeedback(delay);
      useEffect(() => {
        controller.flash(true);
      }, [controller.flash]);
      return <text>{controller.feedback ? controller.feedback.label : "IDLE"}</text>;
    }
    const ui = await testRender(<box style={{ width: "100%" }}><Harness delay={40} /></box>, {
      width: 80,
      height: 3,
    });
    try {
      await ui.flush();
      expect(ui.captureCharFrame()).toContain("Copied to clipboard");
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 90));
        await ui.flush();
      });
      expect(ui.captureCharFrame()).toContain("IDLE");
    } finally {
      ui.renderer.destroy();
    }
  });

  test("App wires the shared hook and no longer keeps a 3000ms copy timer", () => {
    const app = READ("./App.tsx");
    expect(app).toContain("useCopyFeedback");
    expect(app).not.toContain("copyToastTimerRef");
    expect(app).not.toMatch(/setTimeout\([^)]*,\s*3000\)/);
    // A thrown OSC52 write flashes the failure chip; success flashes only after
    // the write returns.
    expect(app).toMatch(/copyToClipboardOSC52\(text\);/);
    expect(app).toMatch(/flashCopyFeedback\(true\)/);
    expect(app).toMatch(/flashCopyFeedback\(false\)/);
  });

  test("App shows failure chip for a throwing OSC52 copy and reverts after ~2.5s", async () => {
    __setChatTransportForTests(
      makeTransport(async (content, mode, callbacks) => {
        callbacks.onMessages((previous) => [
          ...previous,
          { id: "user-polish", role: "user", content, timestamp: Date.now(), mode },
        ]);
      }),
    );
    const ui = await testRender(<DialogProvider><App /></DialogProvider>, {
      width: 80,
      height: 32,
    });
    try {
      await settle(ui);
      // One message so /copy has content.
      await act(async () => {
        await ui.mockInput.typeText("复制测试");
        await ui.flush();
        ui.mockInput.pressEnter();
        await ui.flush();
      });
      await settle(ui, 60);

      const original = ui.renderer.copyToClipboardOSC52.bind(ui.renderer);
      ui.renderer.copyToClipboardOSC52 = () => {
        throw new Error("clipboard unavailable");
      };
      try {
        await act(async () => {
          await ui.mockInput.typeText("/copy");
          await ui.flush();
          ui.mockInput.pressEnter();
          await ui.flush();
        });
        await settle(ui, 60);
        const failed = ui.captureCharFrame();
        expect(failed).toContain("复制失败");
        expect(failed).not.toContain("Copied to clipboard");
        // Unifies to the 2500ms window: after it, the chip is gone.
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 2600));
          await ui.flush();
        });
        expect(ui.captureCharFrame()).not.toContain("复制失败");
      } finally {
        ui.renderer.copyToClipboardOSC52 = original;
      }
    } finally {
      ui.renderer.destroy();
    }
  }, 30_000);
});

describe("long file names keep their suffix", () => {
  test("compound suffixes split as one unit", () => {
    expect(COMPOUND_SUFFIXES).toContain(".tar.gz");
    expect(splitCompoundSuffix("archive.tar.gz")).toEqual({
      stem: "archive",
      suffix: ".tar.gz",
    });
    expect(splitCompoundSuffix("bundle.min.js")).toEqual({ stem: "bundle", suffix: ".min.js" });
    expect(splitCompoundSuffix(".gitignore")).toEqual({ stem: ".gitignore", suffix: "" });
  });

  test("middle ellipsis preserves the suffix within the cell budget", () => {
    const name = "实验报告-第3章 HDFS分布式文件系统_阮心一.docx";
    const clipped = middleEllipsisFileName(name, 26);
    expect(displayWidth(clipped)).toBeLessThanOrEqual(26);
    expect(clipped).toContain("…");
    expect(clipped.startsWith("实验报告")).toBe(true);
    expect(clipped.endsWith(".docx")).toBe(true);

    const tarball = middleEllipsisFileName("very-long-release-asset-name.tar.gz", 20);
    expect(displayWidth(tarball)).toBeLessThanOrEqual(20);
    expect(tarball.endsWith(".tar.gz")).toBe(true);

    const fits = "short.txt";
    expect(middleEllipsisFileName(fits, 20)).toBe(fits);
    const split = splitFileNameForWidth("a.txt", 20);
    expect(split.truncated).toBe(false);

    // Even when the suffix alone is too wide, both ends survive.
    const tiny = middleEllipsisFileName("reallylongname.verylongextension", 8);
    expect(displayWidth(tiny)).toBeLessThanOrEqual(8);
    expect(tiny).toContain("…");
  });

  test("real attachment lines use the shared splitter", () => {
    expect(READ("./clipboard.ts")).toContain("middleEllipsisFileName");
    expect(READ("./App.tsx")).toContain("middleEllipsisFileName");
    expect(READ("./App.tsx")).toContain("formatAttachmentLabels");
  });
});

describe("terminal polish guardrails", () => {
  const SRC = [
    "./App.tsx",
    "./ToolCard.tsx",
    "./statusBar.ts",
    "./todoDock.ts",
    "./ApprovalDialog.tsx",
    "./QuestionDialog.tsx",
    "./PlanPane.tsx",
    "./dialog/DialogSelect.tsx",
    "./lib/displayColumns.ts",
    "./lib/fileName.ts",
    "./lib/copyFeedback.ts",
  ];

  test("no CSS blur / spring / keyframe animation in the terminal render path", () => {
    for (const file of SRC) {
      const source = READ(file);
      expect(source).not.toMatch(/backdrop-filter/);
      expect(source).not.toMatch(/filter:\s*["'\`]?blur/);
      expect(source).not.toMatch(/\bblur\(/);
      expect(source).not.toMatch(/animation:/);
      expect(source).not.toMatch(/@keyframes/);
      expect(source).not.toMatch(/\bspring\b/i);
      expect(source).not.toMatch(/stiffness|damping/);
    }
  });

  test("no per-character reveal timers (streaming text is plain terminal cells)", () => {
    const app = READ("./App.tsx");
    expect(app).not.toMatch(/rxy-stream-glyph|--reveal-delay|stream-reveal/);
    expect(app).not.toContain("requestAnimationFrame");
    // The only copy timer is the shared 2500ms feedback window.
    expect(app).not.toMatch(/setTimeout\([^)]*,\s*(?:3000|90|80|60)\)/);
  });

  test("composer is a single field shell with display-cell edges", () => {
    const app = READ("./App.tsx");
    // One shell surface for header + attachment + input rows (no nested C.bg).
    expect(app).toContain("backgroundColor: C.field");
    expect(app).toContain("composerInnerWidth");
    expect(app).toContain("alignEdges(");
    expect(app).not.toContain("clipComposerLine");
    expect(app).toContain("attachmentEdges");
  });

  test("DialogSelect footer can right-align numeric/age cells", async () => {
    const ui = await testRender(
      <DialogSelect
        title="会话"
        options={[
          { id: "a", title: "alpha", footer: "3d", value: "a" },
          { id: "b", title: "beta", footer: "12d", value: "b" },
        ]}
        footerAlign="end"
        onClose={() => {}}
      />,
      { width: 60, height: 12 },
    );
    try {
      await ui.flush();
      const frame = ui.captureCharFrame();
      const ageLines = frame
        .split("\n")
        .filter((line) => /\b(3d|12d)\b/.test(line));
      expect(ageLines.length).toBe(2);
      // Right edges (excluding border/padding) are identical: the age cells
      // sit on the same display column although "3d" is shorter than "12d".
      const rightEdges = ageLines.map((line) =>
        displayWidth(line.slice(0, line.lastIndexOf("│")).trimEnd()),
      );
      expect(rightEdges[0]).toBe(rightEdges[1]);
    } finally {
      ui.renderer.destroy();
    }
  });
});
