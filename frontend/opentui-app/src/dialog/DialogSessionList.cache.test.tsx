/**
 * /session stale-while-revalidate 缓存（2026-10-11）：
 * 二次打开先渲染缓存行，后台刷新成功后替换；刷新失败保留缓存行并提示。
 * 不用 mock.module（全量跑时会泄漏到后续测试文件）——走 transport 注入桩。
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { act } from "react";
import {
  __setChatTransportForTests,
  resetChatTransportForTests,
} from "../transport/index.ts";
import type { ChatTransport, SessionListRow } from "../transport/types.ts";
import {
  DialogSessionList,
  __clearSessionListCacheForTests,
} from "./DialogSessionList.tsx";

let resolvers: Array<(rows: SessionListRow[]) => void> = [];
let rejecters: Array<(err: unknown) => void> = [];

const fakeTransport: ChatTransport = {
  // getChatTransport 用 kind 判缓存归属；缺 kind 的桩会被当作错误管道丢弃。
  kind: "stdio",
  listSessions: () =>
    new Promise<SessionListRow[]>((resolve, reject) => {
      resolvers.push(resolve);
      rejecters.push(reject);
    }),
  pinSession: async () => {},
  forkSession: async (sessionId: string) => ({
    session_id: `${sessionId}-fork`,
    title: "FORKED",
    display_title: "FORKED",
    date_group: "Today",
  }),
  renameSession: async (sessionId: string, title: string) => ({
    session_id: sessionId,
    title,
    display_title: title,
    date_group: "Today",
  }),
} as unknown as ChatTransport;

const ROW_A: SessionListRow = {
  session_id: "s-a",
  title: "缓存行_A",
  display_title: "缓存行_A",
  date_group: "Today",
};
const ROW_B: SessionListRow = {
  session_id: "s-b",
  title: "新鲜行_B",
  display_title: "新鲜行_B",
  date_group: "Today",
};

const noop = () => {};
const dialogProps = { onClose: noop, onLoaded: noop };

/** 等 reload() 从 mount effect 里真正发出 listSessions（flush() 不保证 effect 已跑）。 */
async function waitForCalls(n: number): Promise<void> {
  for (let i = 0; i < 50 && resolvers.length < n; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  expect(resolvers.length).toBe(n);
}

/** 成功加载一次并关闭，把 rows 写入模块级缓存。 */
async function seedCache(rows: SessionListRow[]): Promise<void> {
  const before = resolvers.length;
  const { flush, renderer } = await testRender(
    <DialogSessionList {...dialogProps} />,
    { width: 80, height: 24 },
  );
  try {
    await flush();
    await waitForCalls(before + 1);
    await act(async () => {
      resolvers[before]!(rows);
      await Promise.resolve();
    });
  } finally {
    renderer.destroy();
  }
}

describe("DialogSessionList stale-while-revalidate cache", () => {
  beforeEach(() => {
    __clearSessionListCacheForTests();
    resolvers = [];
    rejecters = [];
    process.env.RXYCODE_TRANSPORT = "stdio";
    __setChatTransportForTests(fakeTransport);
  });

  afterEach(() => {
    resetChatTransportForTests();
    delete process.env.RXYCODE_TRANSPORT;
  });

  test("无缓存首次打开保持原有加载态，成功后渲染行", async () => {
    const { flush, captureCharFrame, waitForFrame, renderer } = await testRender(
      <DialogSessionList {...dialogProps} />,
      { width: 80, height: 24 },
    );
    try {
      await flush();
      expect(captureCharFrame()).toContain("加载中");
      await waitForCalls(1);

      await act(async () => {
        resolvers[0]!([ROW_A]);
        await Promise.resolve();
      });
      const frame = await waitForFrame((text: string) => text.includes("缓存行_A"));
      expect(frame).toContain("缓存行_A");
    } finally {
      renderer.destroy();
    }
  });

  test("第二次打开先渲染缓存行，后台刷新成功后替换", async () => {
    await seedCache([ROW_A]);

    const { flush, captureCharFrame, waitForFrame, renderer } = await testRender(
      <DialogSessionList {...dialogProps} />,
      { width: 80, height: 24 },
    );
    try {
      // 后台刷新挂起：首帧已是缓存行，而不是退回「加载中…」。
      await flush();
      const stale = captureCharFrame();
      expect(stale).toContain("缓存行_A");
      expect(stale).not.toContain("加载中");
      await waitForCalls(2);

      await act(async () => {
        resolvers[1]!([ROW_B]);
        await Promise.resolve();
      });
      const fresh = await waitForFrame((text: string) => text.includes("新鲜行_B"));
      expect(fresh).toContain("新鲜行_B");
      expect(fresh).not.toContain("缓存行_A");
    } finally {
      renderer.destroy();
    }
  });

  test("有缓存时后台刷新失败：保留缓存行，底栏提示刷新失败", async () => {
    await seedCache([ROW_A]);

    const { flush, waitForFrame, renderer } = await testRender(
      <DialogSessionList {...dialogProps} />,
      { width: 80, height: 24 },
    );
    try {
      await flush();
      await waitForCalls(2);
      await act(async () => {
        rejecters[1]!(new Error("RPC timeout: sessions/list"));
        await Promise.resolve();
      });
      const frame = await waitForFrame((text: string) => text.includes("刷新失败"));
      expect(frame).toContain("缓存行_A");
      expect(frame).toContain("刷新失败: RPC timeout: sessions/list");
    } finally {
      renderer.destroy();
    }
  });

  test("关闭的旧弹窗迟到结果不能覆盖新弹窗缓存", async () => {
    const { flush, renderer } = await testRender(
      <DialogSessionList {...dialogProps} />,
      { width: 80, height: 24 },
    );
    await flush();
    await waitForCalls(1);
    renderer.destroy();

    const second = await testRender(<DialogSessionList {...dialogProps} />, {
      width: 80,
      height: 24,
    });
    try {
      await second.flush();
      await waitForCalls(2);
      await act(async () => {
        resolvers[1]!([ROW_B]);
        await Promise.resolve();
      });
      const fresh = await second.waitForFrame((text: string) => text.includes("新鲜行_B"));
      expect(fresh).toContain("新鲜行_B");
      await act(async () => {
        resolvers[0]!([ROW_A]);
        await Promise.resolve();
      });
      expect(second.captureCharFrame()).toContain("新鲜行_B");
      expect(second.captureCharFrame()).not.toContain("缓存行_A");
    } finally {
      second.renderer.destroy();
    }
  });

  test("同一弹窗里置顶后的刷新不被更早的打开刷新覆盖", async () => {
    await seedCache([ROW_A]);
    const view = await testRender(<DialogSessionList {...dialogProps} />, {
      width: 80,
      height: 24,
    });
    try {
      await view.flush();
      await waitForCalls(2);
      await act(async () => {
        view.mockInput.pressKey("f", { ctrl: true });
        await Promise.resolve();
      });
      await waitForCalls(3);
      await act(async () => {
        resolvers[2]!([
          { ...ROW_A, display_title: "FRESH_PINNED", pinned: true, date_group: "Pinned" },
        ]);
        await Promise.resolve();
      });
      await view.waitForFrame((text: string) => text.includes("FRESH_PINNED"));
      await act(async () => {
        resolvers[1]!([{ ...ROW_A, display_title: "STALE_UNPINNED" }]);
        await Promise.resolve();
      });
      const frame = view.captureCharFrame();
      expect(frame).toContain("FRESH_PINNED");
      expect(frame).not.toContain("STALE_UNPINNED");
    } finally {
      view.renderer.destroy();
    }
  });

  test("重命名后的刷新不被更早的打开刷新覆盖", async () => {
    await seedCache([ROW_A]);
    const view = await testRender(<DialogSessionList {...dialogProps} />, {
      width: 80,
      height: 24,
    });
    try {
      await view.flush();
      await waitForCalls(2);
      await act(async () => {
        view.mockInput.pressKey("r", { ctrl: true });
        await Promise.resolve();
      });
      await act(async () => {
        view.mockInput.pressEnter();
        await Promise.resolve();
        await Promise.resolve();
      });
      await waitForCalls(3);
      await act(async () => {
        resolvers[2]!([{ ...ROW_A, display_title: "RENAMED_TITLE" }]);
        await Promise.resolve();
      });
      await view.waitForFrame((text: string) => text.includes("RENAMED_TITLE"));
      await act(async () => {
        resolvers[1]!([{ ...ROW_A, display_title: "STALE_OLD_NAME" }]);
        await Promise.resolve();
      });
      const frame = view.captureCharFrame();
      expect(frame).toContain("RENAMED_TITLE");
      expect(frame).not.toContain("STALE_OLD_NAME");
    } finally {
      view.renderer.destroy();
    }
  });

  test("Fork 后的刷新不被更早的打开刷新覆盖", async () => {
    await seedCache([ROW_A]);
    const view = await testRender(<DialogSessionList {...dialogProps} />, {
      width: 80,
      height: 24,
    });
    try {
      await view.flush();
      await waitForCalls(2);
      await act(async () => {
        view.mockInput.pressKey("f", { ctrl: true, shift: true });
        await Promise.resolve();
      });
      await waitForCalls(3);
      await act(async () => {
        resolvers[2]!([
          { session_id: "s-fork", display_title: "FRESH_FORK", title: "FRESH_FORK", date_group: "Today" },
        ]);
        await Promise.resolve();
      });
      await view.waitForFrame((text: string) => text.includes("FRESH_FORK"));
      await act(async () => {
        resolvers[1]!([{ ...ROW_A, display_title: "STALE_BEFORE_FORK" }]);
        await Promise.resolve();
      });
      const frame = view.captureCharFrame();
      expect(frame).toContain("FRESH_FORK");
      expect(frame).not.toContain("STALE_BEFORE_FORK");
    } finally {
      view.renderer.destroy();
    }
  });

  test("较早的刷新失败不能盖掉较新的成功结果", async () => {
    await seedCache([ROW_A]);
    const view = await testRender(<DialogSessionList {...dialogProps} />, {
      width: 80,
      height: 24,
    });
    try {
      await view.flush();
      await waitForCalls(2);
      await act(async () => {
        view.mockInput.pressKey("f", { ctrl: true });
        await Promise.resolve();
      });
      await waitForCalls(3);
      await act(async () => {
        resolvers[2]!([
          { ...ROW_A, display_title: "FRESH_PINNED", pinned: true, date_group: "Pinned" },
        ]);
        await Promise.resolve();
      });
      await view.waitForFrame((text: string) => text.includes("FRESH_PINNED"));
      await act(async () => {
        rejecters[1]!(new Error("older list failed"));
        await Promise.resolve();
      });
      const frame = view.captureCharFrame();
      expect(frame).toContain("FRESH_PINNED");
      expect(frame).not.toContain("older list failed");
    } finally {
      view.renderer.destroy();
    }
  });

  test("关闭后迟到的置顶不能递增序号或挡住新弹窗刷新", async () => {
    await seedCache([ROW_A]);
    let releasePin: () => void = () => {};
    fakeTransport.pinSession = () =>
      new Promise<void>((resolve) => {
        releasePin = resolve;
      });
    const first = await testRender(<DialogSessionList {...dialogProps} />, {
      width: 80,
      height: 24,
    });
    await first.flush();
    await waitForCalls(2);
    await act(async () => {
      first.mockInput.pressKey("f", { ctrl: true });
      await Promise.resolve();
    });
    first.renderer.destroy();

    const second = await testRender(<DialogSessionList {...dialogProps} />, {
      width: 80,
      height: 24,
    });
    try {
      await second.flush();
      await waitForCalls(3);
      await act(async () => {
        releasePin();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(resolvers.length).toBe(3);
      await act(async () => {
        resolvers[2]!([{ ...ROW_A, display_title: "FRESH_REOPEN" }]);
        await Promise.resolve();
      });
      const frame = await second.waitForFrame((text: string) => text.includes("FRESH_REOPEN"));
      expect(frame).toContain("FRESH_REOPEN");
      expect(frame).not.toContain("STALE_PIN_RELOAD");
    } finally {
      fakeTransport.pinSession = async () => {};
      second.renderer.destroy();
    }
  });

  test("无缓存且加载失败时保持原有错误空态", async () => {
    const { flush, waitForFrame, renderer } = await testRender(
      <DialogSessionList {...dialogProps} />,
      { width: 80, height: 24 },
    );
    try {
      await flush();
      await waitForCalls(1);
      await act(async () => {
        rejecters[0]!(new Error("appserver exited"));
        await Promise.resolve();
      });
      const frame = await waitForFrame((text: string) =>
        text.includes("appserver exited"),
      );
      expect(frame).toContain("appserver exited");
    } finally {
      renderer.destroy();
    }
  });
});
