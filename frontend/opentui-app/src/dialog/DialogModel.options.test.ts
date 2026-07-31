import { describe, expect, test } from "bun:test";
import { buildModelListOptions } from "./DialogModel.options.ts";

describe("buildModelListOptions", () => {
  test("groups models by provider category with recent first", () => {
    const { options, categoryOrder } = buildModelListOptions(
      [
        {
          id: "deepseek-chat",
          name: "deepseek-chat",
          category: "DeepSeek",
          provider_model_id: "deepseek-chat",
        },
        {
          id: "gpt-4o",
          name: "gpt-4o",
          category: "OpenAI",
          provider_model_id: "gpt-4o",
        },
        {
          id: "legacy-model",
          name: "legacy-model",
          provider_model_id: "legacy-model",
        },
      ],
      ["gpt-4o"],
      "deepseek-chat",
    );

    const byId = Object.fromEntries(options.map((o) => [o.id, o]));
    expect(byId["gpt-4o"]?.category).toBe("最近常用");
    expect(byId["deepseek-chat"]?.category).toBe("DeepSeek");
    expect(byId["legacy-model"]?.category).toBe("其他");
    expect(categoryOrder).toEqual(["最近常用", "DeepSeek", "其他", "操作"]);
    expect(options.at(-1)?.id).toBe("__add__");
  });
});
