// run.error 终态事件 → RunView 时间线 error 行的归约契约。
// 运行：bun test src/features/runs/eventReducer.test.ts
import { describe, expect, test } from "bun:test"
import { reduceEvents, type RunEvent } from "./eventReducer"

const MODEL_GONE_DETAIL =
  "模型 deepseek-flash 已被服务商（OpenCode Go）停用，请在模型选择中换一个模型后重试。"
const MODEL_GONE_RAW =
  "APIStatusError: Error code: 410 - {'type': 'error', 'error': {'type': 'ModelDeprecated'}}"

function events(...items: RunEvent[]): RunEvent[] {
  return items
}

describe("run.error → error timeline item", () => {
  test("detail + code + raw 全部进 error 行", () => {
    const { view } = reduceEvents(
      events(
        { seq: 1, type: "run.created", payload: { message: "写个脚本" } },
        {
          seq: 2,
          type: "run.error",
          payload: {
            detail: MODEL_GONE_DETAIL,
            code: "MODEL_UNAVAILABLE",
            raw: MODEL_GONE_RAW,
            model: "deepseek-flash",
            provider: "OpenCode Go",
          },
        },
        { seq: 3, type: "run.status", payload: { status: "failed" } },
      ),
    )
    expect(view.status).toBe("failed")
    const error = view.timeline.find((item) => item.kind === "error")
    expect(error).toBeDefined()
    if (error?.kind !== "error") throw new Error("unreachable")
    expect(error.text).toBe(MODEL_GONE_DETAIL)
    expect(error.code).toBe("MODEL_UNAVAILABLE")
    expect(error.raw).toBe(MODEL_GONE_RAW)
  })

  test("没有 detail 时退到 message", () => {
    const { view } = reduceEvents(
      events({
        seq: 1,
        type: "run.error",
        payload: { message: "工具执行中断", code: "" },
      }),
    )
    const error = view.timeline.find((item) => item.kind === "error")
    expect(error?.kind === "error" && error.text).toBe("工具执行中断")
  })

  test("空文本不产生 error 行", () => {
    const { view } = reduceEvents(
      events({ seq: 1, type: "run.error", payload: {} }),
    )
    expect(view.timeline.some((item) => item.kind === "error")).toBe(false)
  })

  test("普通失败（无 code）仍是 error 行，只是不带 code", () => {
    const { view } = reduceEvents(
      events({
        seq: 1,
        type: "run.error",
        payload: { detail: "构建未完成，请重试。" },
      }),
    )
    const error = view.timeline.find((item) => item.kind === "error")
    expect(error?.kind === "error" && error.code).toBeUndefined()
  })
})
