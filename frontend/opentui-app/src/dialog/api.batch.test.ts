import { describe, expect, mock, test } from "bun:test";

const axiosPost = mock(() =>
  Promise.resolve({
    data: {
      action: "models_added",
      message: "Added 2 models",
      added: ["deepseek-chat", "deepseek-reasoner"],
      skipped: [],
      active: "deepseek-chat",
    },
  }),
);

mock.module("axios", () => ({
  default: {
    post: axiosPost,
    isAxiosError: (err: unknown) =>
      Boolean(err && typeof err === "object" && (err as { isAxiosError?: boolean }).isAxiosError),
  },
  isAxiosError: (err: unknown) =>
    Boolean(err && typeof err === "object" && (err as { isAxiosError?: boolean }).isAxiosError),
}));

const { onboardModelsBatch } = await import("./api.ts");

describe("onboardModelsBatch", () => {
  test("posts batch payload and parses added/skipped/active", async () => {
    axiosPost.mockClear();
    const result = await onboardModelsBatch({
      apiKey: "sk-batch",
      baseUrl: "https://api.deepseek.com/v1",
      modelIds: ["deepseek-chat", "deepseek-reasoner"],
      providerId: "deepseek",
      providerName: "DeepSeek",
      activeModelId: "deepseek-chat",
      skipProbe: true,
    });

    expect(result.ok).toBe(true);
    expect(result.added).toEqual(["deepseek-chat", "deepseek-reasoner"]);
    expect(result.skipped).toEqual([]);
    expect(result.active).toBe("deepseek-chat");
    expect(result.message).toContain("Added");

    const call = axiosPost.mock.calls[0];
    expect(String(call?.[0])).toContain("/models/onboard/batch");
    expect(call?.[1]).toEqual({
      api_key: "sk-batch",
      base_url: "https://api.deepseek.com/v1",
      model_ids: ["deepseek-chat", "deepseek-reasoner"],
      provider_id: "deepseek",
      provider_name: "DeepSeek",
      active_model_id: "deepseek-chat",
      skip_probe: true,
    });
  });

  test("maps axios error to ok=false", async () => {
    axiosPost.mockImplementationOnce(() => {
      const err = Object.assign(new Error("Request failed"), {
        isAxiosError: true,
        response: { data: { detail: "No models were added" } },
      });
      return Promise.reject(err);
    });

    const result = await onboardModelsBatch({
      apiKey: "sk-batch",
      baseUrl: "https://api.deepseek.com/v1",
      modelIds: ["deepseek-chat"],
    });

    expect(result.ok).toBe(false);
    expect(result.added).toEqual([]);
    expect(result.error).toContain("No models were added");
  });
});
