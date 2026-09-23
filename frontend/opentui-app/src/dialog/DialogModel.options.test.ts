import { describe, expect, test } from "bun:test";
import {
  buildModelListOptions,
  modelLimitSummary,
} from "./DialogModel.options.ts";
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
    expect(options.find((o) => o.id === "deepseek/deepseek-v4-flash")?.title).toBe(
      "deepseek-v4-flash · api.deepseek.com",
    );
    expect(options.find((o) => o.id === "opencode-go/deepseek-v4-flash")?.title).toBe(
      "deepseek-v4-flash · opencode.ai",
    );
  });
});

describe("inferProviderFromUrl", () => {
  test("maps known hosts to preset names", () => {
    expect(inferProviderFromUrl("https://api.deepseek.com/v1")).toEqual({
      id: "deepseek",
      name: "DeepSeek",
    });
  });

  test("unknown hosts group by hostname so /model is findable", () => {
    expect(inferProviderFromUrl("https://weird.example/v1")).toEqual({
      id: "custom-weird-example",
      name: "weird.example",
    });
  });
});

describe("modelLimitSummary (Phase 3 M6)", () => {
  test("renders source + value for known sources", () => {
    expect(
      modelLimitSummary({ id: "x", name: "x", limit_source: "catalog_exact_provider", resolved_max_tokens: 65536 }),
    ).toBe("输出目录 65536");
    expect(
      modelLimitSummary({ id: "x", name: "x", limit_source: "explicit_config", resolved_max_tokens: 4096 }),
    ).toBe("输出显式 4096");
  });

  test("unknown_fallback is labeled 兜底, not official max", () => {
    expect(
      modelLimitSummary({ id: "x", name: "x", limit_source: "unknown_fallback", resolved_max_tokens: 32768 }),
    ).toBe("输出兜底 32768");
  });

  test("legacy server (missing fields) renders empty, client does not guess", () => {
    expect(modelLimitSummary({ id: "x", name: "x" })).toBe("");
    expect(
      modelLimitSummary({ id: "x", name: "x", limit_source: "legacy_server", resolved_max_tokens: 0 }),
    ).toBe("");
  });

  test("description includes limit summary when present", () => {
    const { options } = buildModelListOptions(
      [
        {
          id: "demo/m",
          name: "m",
          provider_model_id: "m",
          category: "Demo",
          provider_name: "Demo",
          base_url: "https://api.demo.com/v1",
          limit_source: "catalog_exact_provider",
          resolved_max_tokens: 65536,
        },
      ],
      [],
      "",
    );
    expect(options[0]?.description).toContain("输出目录 65536");
  });
});
