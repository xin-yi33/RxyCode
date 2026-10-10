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
