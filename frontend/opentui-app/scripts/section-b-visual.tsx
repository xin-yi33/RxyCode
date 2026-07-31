/**
 * §B visual acceptance — headless OpenTUI frames for multimodal review.
 * Captures character frames at each B2-relevant stage (mocked network).
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { mock } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { act } from "react";

const OUT = join(import.meta.dir, "../../../artifacts/section-b");
mkdirSync(OUT, { recursive: true });

const PRESETS = [
  { id: "deepseek", name: "DeepSeek", base_url: "https://api.deepseek.com/v1", category: "常用" },
  { id: "openai", name: "OpenAI", base_url: "https://api.openai.com/v1", category: "其他" },
];

const axiosGet = mock((url: string) => {
  if (String(url).endsWith("/models/presets")) {
    return Promise.resolve({ data: { presets: PRESETS } });
  }
  if (String(url).endsWith("/models")) {
    return Promise.resolve({
      data: {
        models: [
          {
            id: "deepseek-chat",
            name: "deepseek-chat",
            nickname: "deepseek-chat",
            provider_model_id: "deepseek-chat",
            category: "DeepSeek",
            provider_name: "DeepSeek",
            active: true,
            base_url: "https://api.deepseek.com/v1",
          },
          {
            id: "deepseek-reasoner",
            name: "deepseek-reasoner",
            nickname: "deepseek-reasoner",
            provider_model_id: "deepseek-reasoner",
            category: "DeepSeek",
            provider_name: "DeepSeek",
            active: false,
            base_url: "https://api.deepseek.com/v1",
          },
          {
            id: "legacy-model",
            name: "legacy-model",
            nickname: "legacy-model",
            provider_model_id: "legacy-model",
            active: false,
            base_url: "https://legacy.example/v1",
          },
        ],
        active: "deepseek-chat",
        recent: ["deepseek-chat"],
      },
    });
  }
  return Promise.resolve({ data: {} });
});

let discoverMode: "ok" | "auth" = "ok";

const axiosPost = mock((url: string, body?: Record<string, unknown>) => {
  void body;
  if (String(url).endsWith("/models/discover")) {
    if (discoverMode === "auth") {
      const err = Object.assign(new Error("Request failed"), {
        isAxiosError: true,
        response: {
          data: {
            detail: { message: "Model discovery failed: 认证失败", error_code: "auth" },
          },
        },
      });
      return Promise.reject(err);
    }
    return Promise.resolve({
      data: {
        models: [
          { id: "deepseek-chat", owned_by: "deepseek" },
          { id: "deepseek-reasoner" },
        ],
      },
    });
  }
  if (String(url).endsWith("/models/onboard/batch")) {
    return Promise.resolve({
      data: {
        action: "models_added",
        message: "已添加 1 个模型，请到 /model 查看",
        added: ["deepseek-reasoner"],
        skipped: ["deepseek-chat"],
        active: "deepseek-reasoner",
      },
    });
  }
  return Promise.resolve({ data: { action: "model_added", message: "ok" } });
});

mock.module("axios", () => ({
  default: {
    get: axiosGet,
    post: axiosPost,
    isAxiosError: (err: unknown) =>
      Boolean(err && typeof err === "object" && (err as { isAxiosError?: boolean }).isAxiosError),
  },
  isAxiosError: (err: unknown) =>
    Boolean(err && typeof err === "object" && (err as { isAxiosError?: boolean }).isAxiosError),
}));

const { DialogAddModel } = await import("../src/dialog/DialogAddModel.tsx");
const { DialogModel } = await import("../src/dialog/DialogModel.tsx");
const { DialogSelect } = await import("../src/dialog/DialogSelect.tsx");

function saveFrame(name: string, frame: string) {
  const path = join(OUT, `${name}.txt`);
  writeFileSync(path, frame, "utf8");
  console.log(`saved ${path}`);
  console.log("--- FRAME", name, "---");
  console.log(frame);
  console.log("--- END ---");
}

async function shotAddModel(name: string, drive: (ctx: Awaited<ReturnType<typeof testRender>>) => Promise<void>) {
  const ctx = await testRender(<DialogAddModel onClose={() => {}} onDone={() => {}} />, {
    width: 90,
    height: 30,
  });
  try {
    await drive(ctx);
    saveFrame(name, ctx.captureCharFrame());
  } finally {
    ctx.renderer.destroy();
  }
}

// B2-1 provider list
await shotAddModel("b2-01-provider-list", async ({ flush }) => {
  await flush();
  await flush();
});

// B2-1 key screen
await shotAddModel("b2-01-api-key", async ({ mockInput, flush, waitForFrame }) => {
  await flush();
  await flush();
  await mockInput.typeText("deepseek");
  await flush();
  await act(async () => {
    mockInput.pressEnter();
  });
  await waitForFrame((f) => f.includes("API Key"));
});

// B2-1 multi-select default all
await shotAddModel("b2-01-multi-default-all", async ({ mockInput, flush, waitForFrame }) => {
  discoverMode = "ok";
  await flush();
  await flush();
  await mockInput.typeText("deepseek");
  await flush();
  await act(async () => {
    mockInput.pressEnter();
  });
  await waitForFrame((f) => f.includes("API Key"));
  await mockInput.typeText("sk-test-key");
  await flush();
  await act(async () => {
    mockInput.pressEnter();
  });
  await waitForFrame((f) => f.includes("deepseek-chat") && f.includes("✓"));
});

// B2-2 after uncheck one (space) — still on multi screen
await shotAddModel("b2-02-multi-after-uncheck", async ({ mockInput, flush, waitForFrame }) => {
  discoverMode = "ok";
  await flush();
  await flush();
  await mockInput.typeText("deepseek");
  await flush();
  await act(async () => {
    mockInput.pressEnter();
  });
  await waitForFrame((f) => f.includes("API Key"));
  await mockInput.typeText("sk-test-key");
  await flush();
  await act(async () => {
    mockInput.pressEnter();
  });
  await waitForFrame((f) => f.includes("deepseek-chat"));
  await act(async () => {
    mockInput.pressKey(" ");
  });
  await flush();
});

// B2-4 auth failure stays on key
await shotAddModel("b2-04-auth-fail-key", async ({ mockInput, flush, waitForFrame }) => {
  discoverMode = "auth";
  await flush();
  await flush();
  await mockInput.typeText("deepseek");
  await flush();
  await act(async () => {
    mockInput.pressEnter();
  });
  await waitForFrame((f) => f.includes("API Key"));
  await mockInput.typeText("sk-bad");
  await flush();
  await act(async () => {
    mockInput.pressEnter();
  });
  await waitForFrame((f) => f.includes("API Key") && f.includes("认证"));
  discoverMode = "ok";
});

// B2-5 custom http rejected
await shotAddModel("b2-05-custom-http-reject", async ({ mockInput, flush, waitForFrame }) => {
  await flush();
  await flush();
  await mockInput.typeText("自定义");
  await flush();
  await act(async () => {
    mockInput.pressEnter();
  });
  await waitForFrame((f) => f.includes("API URL"));
  await mockInput.typeText("http://example.com/v1");
  await flush();
  await act(async () => {
    mockInput.pressEnter();
  });
  await flush();
});

// B2-3 DialogModel grouped
{
  const ctx = await testRender(
    <DialogModel onClose={() => {}} onSwitched={() => {}} activeModel="deepseek-chat" />,
    { width: 90, height: 30 },
  );
  try {
    await ctx.flush();
    await ctx.flush();
    await ctx.waitForFrame((f) => f.includes("DeepSeek") || f.includes("deepseek-chat"));
    saveFrame("b2-03-model-grouped", ctx.captureCharFrame());
  } finally {
    ctx.renderer.destroy();
  }
}

// B2-6 multi select with checkmarks (explicit multi DialogSelect)
{
  const options = [
    { id: "deepseek-chat", title: "deepseek-chat", category: "可用模型", value: "deepseek-chat" },
    { id: "deepseek-reasoner", title: "deepseek-reasoner", category: "可用模型", value: "deepseek-reasoner" },
  ];
  const ctx = await testRender(
    <DialogSelect
      title="DeepSeek · 选择要添加的模型"
      options={options}
      multi
      defaultSelectedIds={options.map((o) => o.id)}
      onClose={() => {}}
      onConfirm={() => {}}
    />,
    { width: 90, height: 28 },
  );
  try {
    await ctx.flush();
    saveFrame("b2-06-multi-select-ui", ctx.captureCharFrame());
  } finally {
    ctx.renderer.destroy();
  }
}

writeFileSync(
  join(OUT, "manifest.json"),
  JSON.stringify(
    {
      generated_at: new Date().toISOString(),
      frames: [
        "b2-01-provider-list",
        "b2-01-api-key",
        "b2-01-multi-default-all",
        "b2-02-multi-after-uncheck",
        "b2-03-model-grouped",
        "b2-04-auth-fail-key",
        "b2-05-custom-http-reject",
        "b2-06-multi-select-ui",
      ],
    },
    null,
    2,
  ),
);
console.log("done");
