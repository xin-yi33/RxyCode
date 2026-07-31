/**
 * Add-model flow: provider presets and discovered model ids reach DialogSelect.
 *
 * Asserts the dialog shape: a searchable list with a block cursor rather than a
 * numbered menu, and that no model id is ever hard-coded in the frontend.
 */

import { describe, expect, mock, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { act } from "react";

const PRESETS = [
  { id: "deepseek", name: "DeepSeek", base_url: "https://api.deepseek.com/v1", category: "常用" },
  { id: "openai", name: "OpenAI", base_url: "https://api.openai.com/v1", category: "其他" },
];

const axiosGet = mock((url: string) => {
  if (url.endsWith("/models/presets")) {
    return Promise.resolve({ data: { presets: PRESETS } });
  }
  return Promise.resolve({ data: { models: [], active: "", recent: [] } });
});

const axiosPost = mock((url: string, body?: Record<string, unknown>) => {
  void body;
  if (url.endsWith("/models/discover")) {
    return Promise.resolve({
      data: {
        models: [{ id: "deepseek-chat", owned_by: "deepseek" }, { id: "deepseek-reasoner" }],
      },
    });
  }
  return Promise.resolve({ data: { action: "model_added", message: "ok" } });
});

mock.module("axios", () => ({
  default: { get: axiosGet, post: axiosPost, isAxiosError: () => false },
  isAxiosError: () => false,
}));

const { DialogAddModel, buildProviderOptions, buildModelOptions } = await import(
  "./DialogAddModel.tsx"
);

describe("add-model option builders", () => {
  test("provider options carry base URLs but never a model id", () => {
    const options = buildProviderOptions(PRESETS);

    const deepseek = options.find((o) => o.id === "deepseek");
    expect(deepseek?.title).toBe("DeepSeek");
    expect(deepseek?.description).toBe("https://api.deepseek.com/v1");
    expect(deepseek?.category).toBe("常用");
    // A provider row must not pin a model id under any key.
    expect(JSON.stringify(options)).not.toMatch(/gpt-4o|deepseek-chat|ep-2025|moonshot-v1/);
  });

  test("a custom escape hatch is always offered", () => {
    expect(buildProviderOptions([]).map((o) => o.id)).toEqual(["__custom__"]);
  });

  test("discovered ids become options plus a manual-entry row", () => {
    const options = buildModelOptions([
      { id: "deepseek-chat", owned_by: "deepseek" },
      { id: "deepseek-reasoner" },
    ]);

    expect(options.map((o) => o.id)).toEqual([
      "deepseek-chat",
      "deepseek-reasoner",
      "__manual_model__",
    ]);
    expect(options[0]!.description).toBe("deepseek");
  });
});

describe("DialogAddModel (headless mockInput)", () => {
  test("first screen is a searchable provider list, not a numbered menu", async () => {
    const { flush, captureCharFrame, renderer } = await testRender(
      <DialogAddModel onClose={() => {}} onDone={() => {}} />,
      { width: 80, height: 28 },
    );
    try {
      await flush();
      await flush();
      const frame = captureCharFrame();

      expect(frame).toContain("添加模型");
      expect(frame).toContain("搜索服务商");
      expect(frame).toContain("DeepSeek");
      expect(frame).toContain("常用");
      // no numbered preset dump and no "pick a number" prompt
      expect(frame).not.toContain("输入 1-10");
      expect(frame).not.toContain("【官方预设模型】");
      expect(frame).not.toContain("【已使用模型】");
      expect(frame).not.toMatch(/gpt-4o|ep-2025/);
    } finally {
      renderer.destroy();
    }
  });

  test("search filters the provider list", async () => {
    const { mockInput, flush, captureCharFrame, renderer } = await testRender(
      <DialogAddModel onClose={() => {}} onDone={() => {}} />,
      { width: 80, height: 28 },
    );
    try {
      await flush();
      await flush();
      await mockInput.typeText("openai");
      await flush();
      const frame = captureCharFrame();

      expect(frame).toContain("OpenAI");
      expect(frame).not.toContain("DeepSeek");
    } finally {
      renderer.destroy();
    }
  });

  test("provider → key → discover puts real model ids in a searchable list", async () => {
    const { mockInput, flush, waitForFrame, captureCharFrame, renderer } = await testRender(
      <DialogAddModel onClose={() => {}} onDone={() => {}} />,
      { width: 80, height: 28 },
    );
    try {
      await flush();
      await flush();

      // pick DeepSeek by filtering, then Enter.
      // Stage transitions are React state updates driven from a useKeyboard
      // handler, so they must be flushed inside act() to repaint.
      await mockInput.typeText("deepseek");
      await flush();
      await act(async () => {
        mockInput.pressEnter();
      });
      const keyScreen = await waitForFrame((frame) => frame.includes("API Key"));
      expect(keyScreen).toContain("API Key");

      await mockInput.typeText("sk-test-key");
      await flush();
      const masked = captureCharFrame();
      // the credential is never echoed verbatim
      expect(masked).not.toContain("sk-test-key");
      expect(masked).toContain("*");

      await act(async () => {
        mockInput.pressEnter();
      });
      const modelScreen = await waitForFrame((frame) => frame.includes("deepseek-chat"));
      expect(modelScreen).toContain("deepseek-chat");
      expect(modelScreen).toContain("deepseek-reasoner");
      expect(modelScreen).toContain("搜索模型");

      const discoverCall = axiosPost.mock.calls.find((call) =>
        String(call[0]).endsWith("/models/discover"),
      );
      expect(discoverCall).toBeDefined();
      // the base URL comes from the backend preset, not a frontend constant
      expect(discoverCall?.[1]?.base_url).toBe("https://api.deepseek.com/v1");
    } finally {
      renderer.destroy();
    }
  });
});
