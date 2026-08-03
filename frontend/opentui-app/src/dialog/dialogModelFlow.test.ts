import { describe, expect, test } from "bun:test";
import {
  interpretModelSwitchResult,
  modelSwitchCommand,
} from "./dialogModelFlow.ts";

describe("modelSwitchCommand", () => {
  test("uses namespaced model id verbatim", () => {
    expect(modelSwitchCommand("deepseek/deepseek-chat")).toBe(
      "/model deepseek/deepseek-chat",
    );
  });
});

describe("interpretModelSwitchResult", () => {
  test("http failure stays open with explicit error", () => {
    expect(
      interpretModelSwitchResult("m2", { ok: false, error: "无法连接 API 服务" }),
    ).toEqual({ ok: false, error: "无法连接 API 服务" });
  });

  test("server error action does not count as success", () => {
    expect(
      interpretModelSwitchResult("m2", {
        ok: false,
        action: "error",
        message: "Model not found: m2",
        error: "Model not found: m2",
      }),
    ).toEqual({ ok: false, error: "Model not found: m2" });
  });

  test("only model_changed closes dialog", () => {
    expect(
      interpretModelSwitchResult("m2", {
        ok: true,
        action: "model_changed",
        message: "Model switched: m2",
      }),
    ).toEqual({
      ok: true,
      modelId: "m2",
      message: "Model switched: m2",
    });
  });
});
