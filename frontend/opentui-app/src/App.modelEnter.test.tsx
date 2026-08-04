/**
 * Headless App-level: type /model + Enter should open model dialog.
 */
import { afterEach, describe, expect, mock, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { DialogProvider } from "./dialog/DialogHost.tsx";

const axiosGet = mock((url: string) => {
  if (String(url).includes("/models")) {
    return Promise.resolve({
      data: {
        models: [
          {
            id: "provider/a",
            name: "provider/a",
            nickname: "Model A",
            category: "Provider",
          },
          {
            id: "provider/b",
            name: "provider/b",
            nickname: "Model B",
            category: "Provider",
          },
        ],
        active: "provider/a",
        recent: [],
      },
    });
  }
  return Promise.resolve({
    data: { model: "provider/a", mode: "build", context_used_k: 1, context_max_k: 256 },
  });
});

const axiosPost = mock(() =>
  Promise.resolve({ data: { action: "model_changed", message: "ok", ok: true } }),
);

mock.module("axios", () => ({
  default: {
    get: axiosGet,
    post: axiosPost,
    isAxiosError: () => false,
  },
}));

process.env.RXYCODE_TRANSPORT = "http";
process.env.RXYCODE_API_URL = "http://127.0.0.1:9";
process.env.RXYCODE_API_TOKEN = "test";

const { default: App } = await import("./App.tsx");

describe("App /model Enter", () => {
  afterEach(() => {
    axiosGet.mockClear();
    axiosPost.mockClear();
  });

  test("typing /model then Enter opens model picker", async () => {
    const { mockInput, flush, captureCharFrame, renderer } = await testRender(
      <DialogProvider>
        <App />
      </DialogProvider>,
      { width: 100, height: 36 },
    );

    try {
      await flush();
      await mockInput.typeText("/model");
      await flush();
      mockInput.pressEnter();
      await flush();
      // Allow DialogModel fetch + render
      await new Promise((r) => setTimeout(r, 200));
      await flush();

      const frame = captureCharFrame();
      expect(frame).toContain("选择模型");
      expect(frame).toMatch(/Model A|provider\/a/);
    } finally {
      renderer.destroy();
    }
  }, 20000);

  test("typing /mod then Enter expands and opens model picker", async () => {
    const { mockInput, flush, captureCharFrame, renderer } = await testRender(
      <DialogProvider>
        <App />
      </DialogProvider>,
      { width: 100, height: 36 },
    );

    try {
      await flush();
      await mockInput.typeText("/mod");
      await flush();
      mockInput.pressEnter();
      await flush();
      await new Promise((r) => setTimeout(r, 200));
      await flush();

      const frame = captureCharFrame();
      expect(frame).toContain("选择模型");
    } finally {
      renderer.destroy();
    }
  }, 20000);
});
