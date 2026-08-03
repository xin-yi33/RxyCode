import { describe, expect, test } from "bun:test";
import { buildModelListOptions } from "./DialogModel.options.ts";
import { inferProviderFromUrl } from "./providerGroup.ts";

describe("buildModelListOptions", () => {
  test("keeps models under provider groups; recent are duplicates at top", () => {
    const { options, categoryOrder } = buildModelListOptions(
      [
        {
          id: "deepseek/deepseek-chat",
          name: "deepseek-chat",
          nickname: "deepseek-chat",
          category: "DeepSeek",
          provider_name: "DeepSeek",
          provider_model_id: "deepseek-chat",
        },
        {
          id: "opencode-go/deepseek-v4-flash",
          name: "deepseek-v4-flash",
          nickname: "deepseek-v4-flash",
          category: "OpenCode Go",
          provider_name: "OpenCode Go",
          provider_model_id: "deepseek-v4-flash",
        },
        {
          id: "legacy-model",
          name: "legacy-model",
          provider_model_id: "legacy-model",
        },
      ],
      ["deepseek/deepseek-chat"],
      "deepseek/deepseek-chat",
    );

    const recent = options.filter((o) => o.category === "最近常用");
    const deepseek = options.filter((o) => o.category === "DeepSeek");
    const go = options.filter((o) => o.category === "OpenCode Go");
    const other = options.filter((o) => o.category === "其他");

    expect(recent.map((o) => o.value)).toEqual(["deepseek/deepseek-chat"]);
    expect(deepseek.map((o) => o.title)).toEqual(["deepseek-chat"]);
    expect(go.map((o) => o.title)).toEqual(["deepseek-v4-flash"]);
    expect(other.map((o) => o.title)).toEqual(["legacy-model"]);
    expect(go[0]?.description).toContain("OpenCode Go");
    expect(categoryOrder).toEqual([
      "最近常用",
      "DeepSeek",
      "OpenCode Go",
      "其他",
      "操作",
    ]);
    expect(options.at(-1)?.id).toBe("__add__");
  });

  test("same vendor id from two endpoints stays in separate groups", () => {
    const { options } = buildModelListOptions(
      [
        {
          id: "deepseek/deepseek-v4-flash",
          name: "deepseek-v4-flash",
          nickname: "deepseek-v4-flash",
          category: "DeepSeek",
          provider_name: "DeepSeek",
          provider_model_id: "deepseek-v4-flash",
          base_url: "https://api.deepseek.com/v1",
        },
        {
          id: "opencode-go/deepseek-v4-flash",
          name: "deepseek-v4-flash",
          nickname: "deepseek-v4-flash",
          category: "OpenCode Go",
          provider_name: "OpenCode Go",
          provider_model_id: "deepseek-v4-flash",
          base_url: "https://opencode.ai/zen/go/v1",
        },
      ],
      [],
      "deepseek/deepseek-v4-flash",
    );
    expect(options.filter((o) => o.category === "DeepSeek")).toHaveLength(1);
    expect(options.filter((o) => o.category === "OpenCode Go")).toHaveLength(1);
  });
});

describe("inferProviderFromUrl", () => {
  test("maps known hosts to preset names", () => {
    expect(inferProviderFromUrl("https://api.deepseek.com/v1")).toEqual({
      id: "deepseek",
      name: "DeepSeek",
    });
  });

  test("falls back to 其他 for unknown hosts", () => {
    expect(inferProviderFromUrl("https://weird.example/v1")).toEqual({
      id: "custom",
      name: "其他",
    });
  });
});
