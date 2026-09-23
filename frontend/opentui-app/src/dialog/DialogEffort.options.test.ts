/**
 * DialogEffort 纯逻辑测试：档位选项构建（照 DialogModel.options.test.ts 模式，
 * 不渲染 OpenTUI 树）。
 */
import { describe, expect, test } from "bun:test";
import { buildOptions, EFFORT_DESCRIPTIONS } from "./DialogEffort.tsx";

function model(id: string, effortOptions?: string[]): { id: string; name: string; effort_options?: string[] } {
  const m: { id: string; name: string; effort_options?: string[] } = { id, name: id };
  if (effortOptions) m.effort_options = effortOptions;
  return m;
}

describe("buildOptions", () => {
  test("active model determines effort options", () => {
    const models = [
      model("deepseek", ["low", "high", "max"]),
      model("openai", ["low", "medium", "high"]),
    ];
    const built = buildOptions(models as never, "openai");
    expect(built.modelName).toBe("openai");
    expect(built.options.map((o) => o.value)).toEqual(["low", "medium", "high"]);
  });

  test("falls back to first model when active id unknown", () => {
    const built = buildOptions([model("deepseek", ["low", "high", "max"])] as never, "missing");
    expect(built.options.map((o) => o.value)).toEqual(["low", "high", "max"]);
  });

  test("no effort_options means unsupported (empty list)", () => {
    const built = buildOptions([model("anthropic")] as never, "anthropic");
    expect(built.options).toEqual([]);
    expect(built.modelName).toBe("anthropic");
  });

  test("known vendor levels carry Chinese descriptions", () => {
    const built = buildOptions([model("deepseek", ["low", "high", "max"])] as never, "deepseek");
    expect(built.options[1].description).toBe(EFFORT_DESCRIPTIONS["high"]);
  });

  test("unknown level keeps a fallback description", () => {
    const built = buildOptions([model("custom", ["custom-x"])] as never, "custom");
    expect(built.options[0].description).toBe("自定义档位");
  });

  test("vendor builder still does not inject Default", () => {
    const built = buildOptions([model("deepseek", ["low", "max"])] as never, "deepseek");
    expect(built.options.map((o) => o.value)).toEqual(["low", "max"]);
  });
});
