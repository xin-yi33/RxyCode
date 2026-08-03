import type { CommandResult } from "../transport/httpAdmin.ts";

export type ModelSwitchResult =
  | { ok: true; modelId: string; message: string }
  | { ok: false; error: string };

/** Pure model-switch handler — unit-tested without OpenTUI render tree. */
export function interpretModelSwitchResult(
  modelId: string,
  result: CommandResult,
): ModelSwitchResult {
  if (!result.ok) {
    return {
      ok: false,
      error: result.error || result.message || "无法连接 API 服务",
    };
  }
  if (result.action !== "model_changed") {
    return {
      ok: false,
      error: result.message || result.error || "切换失败",
    };
  }
  return {
    ok: true,
    modelId,
    message: String(result.message || `已切换: ${modelId}`),
  };
}

export function modelSwitchCommand(modelId: string): string {
  return `/model ${modelId}`;
}
