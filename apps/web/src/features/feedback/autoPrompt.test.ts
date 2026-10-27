// 自动询问灵敏度语料 —— 标签是固定期望，不得为迁就实现修改。
// 运行：bun test src/features/feedback/autoPrompt.test.ts
import { describe, expect, test } from "bun:test"
import {
  AutoPromptPolicy,
  PROMPT_DELAY_MS,
  type GateContext,
  type RunTerminalSignal,
} from "./autoPrompt"

let now = 0
const clock = () => now
function advance(ms: number) {
  now += ms
}

const OPEN_GATES: GateContext = {
  enabled: true,
  visible: true,
  composerEmpty: true,
  composerFocusedWithinMs: null,
  modalOpen: false,
}

function gates(over: Partial<GateContext> = {}): () => GateContext {
  return () => ({ ...OPEN_GATES, ...over })
}

function mkSignal(over: Partial<RunTerminalSignal> = {}): RunTerminalSignal {
  return {
    runId: `run-${Math.random().toString(36).slice(2, 10)}`,
    sessionId: "sess-1",
    status: "succeeded",
    finalText: "这是正常的回答",
    toolFailures: 0,
    stoppedByUser: false,
    durationMs: 30_000,
    leaseEpochs: 0,
    prompt: "帮我写一个快速排序",
    live: true,
    ...over,
  }
}

type Harness = {
  policy: AutoPromptPolicy
  // 终态→(可选 followup)→tick 到展示点，返回是否最终展示。
  drive: (
    signal: RunTerminalSignal,
    followup?: { text: string; elapsedMs: number },
  ) => boolean
}

function harness(
  gatesFn: () => GateContext = gates(),
  state: ConstructorParameters<typeof AutoPromptPolicy>[2] = {},
): Harness {
  const policy = new AutoPromptPolicy(clock, [], state, gatesFn)
  const drive: Harness["drive"] = (signal, followup) => {
    let event = policy.runTerminal(signal, now)
    if (followup) {
      now += followup.elapsedMs
      event = policy.followupSent(followup.text, now)
    }
    if (event.kind === "scheduled") {
      now += event.delayMs + 1
      event = policy.tick()
    }
    return event.kind === "show"
  }
  return { policy, drive }
}

function showAfter(
  policy: AutoPromptPolicy,
  signal: RunTerminalSignal,
  followup?: { text: string; elapsedMs: number },
): boolean {
  let event = policy.runTerminal(signal, now)
  if (followup) {
    now += followup.elapsedMs
    event = policy.followupSent(followup.text, now)
  }
  if (event.kind === "scheduled") {
    now += event.delayMs + 1
    event = policy.tick()
  }
  return event.kind === "show"
}

// ---- 应弹（P1–P8） ----------------------------------------------------------

const POSITIVE: Array<{
  id: string
  build: () => { signal: RunTerminalSignal; followup?: { text: string; elapsedMs: number } }
}> = [
  { id: "P1", build: () => ({ signal: mkSignal({ status: "failed" }) }) },
  { id: "P2", build: () => ({ signal: mkSignal({ status: "recovery_required" }) }) },
  { id: "P3", build: () => ({ signal: mkSignal({ finalText: "" }) }) },
  {
    id: "P4",
    build: () => ({
      signal: mkSignal({ prompt: "帮我写一个快速排序" }),
      followup: { text: "重新：帮我写一个快速排序", elapsedMs: 60_000 },
    }),
  },
  {
    id: "P5",
    build: () => ({
      // 强抱怨 + 与原 prompt 高相似（该文本 Dice≈0.8 ≥ 0.8 阈值）。
      signal: mkSignal({ prompt: "帮我写一个快速排序" }),
      followup: { text: "帮我写一个快速排序还是不行", elapsedMs: 60_000 },
    }),
  },
  {
    id: "P6",
    build: () => ({
      signal: mkSignal({
        status: "cancelled",
        stoppedByUser: true,
        durationMs: 45_000,
      }),
      followup: { text: "答非所问", elapsedMs: 30_000 },
    }),
  },
  {
    id: "P7",
    build: () => ({
      // 上一 run 已命中强抱怨（见套件 setup），本 run 后续又「还是不行」。
      signal: mkSignal({}),
      followup: { text: "还是不行", elapsedMs: 60_000 },
    }),
  },
  {
    id: "P8",
    build: () => ({
      signal: mkSignal({
        status: "cancelled",
        stoppedByUser: true,
        durationMs: 30_000,
        leaseEpochs: 2,
      }),
      followup: { text: "错了", elapsedMs: 20_000 },
    }),
  },
]

// ---- 不弹（N1–N14） ---------------------------------------------------------

const NEGATIVE: Array<{
  id: string
  build: () => { signal: RunTerminalSignal; followup?: { text: string; elapsedMs: number } }
}> = [
  { id: "N1", build: () => ({ signal: mkSignal({}) }) },
  { id: "N2", build: () => ({ signal: mkSignal({ toolFailures: 2 }) }) },
  { id: "N3", build: () => ({ signal: mkSignal({ toolFailures: 5 }) }) },
  {
    id: "N4",
    build: () => ({
      signal: mkSignal({ status: "cancelled", stoppedByUser: true, durationMs: 3_000 }),
    }),
  },
  {
    id: "N5",
    build: () => ({
      signal: mkSignal({ status: "cancelled", stoppedByUser: true, durationMs: 60_000 }),
    }),
  },
  {
    id: "N6",
    build: () => ({
      signal: mkSignal({ prompt: "帮我写一个快速排序" }),
      followup: { text: "不对，换成 Python 写", elapsedMs: 60_000 },
    }),
  },
  {
    id: "N7",
    build: () => ({
      signal: mkSignal(),
      followup: { text: "继续", elapsedMs: 60_000 },
    }),
  },
  {
    id: "N8",
    build: () => ({
      signal: mkSignal({ prompt: "帮我写一个快速排序" }),
      followup: { text: "帮我写一个快速排序", elapsedMs: 600_000 },
    }),
  },
  { id: "N9", build: () => ({ signal: mkSignal({ status: "failed", live: false }) }) },
  {
    id: "N10",
    build: () => ({
      signal: mkSignal({ prompt: "帮我写一个快速排序" }),
      followup: { text: "还是不行", elapsedMs: 60_000 },
    }),
  },
  {
    id: "N11",
    build: () => ({
      signal: mkSignal({
        status: "cancelled",
        stoppedByUser: true,
        durationMs: 4_000,
        prompt: "帮我写一个快速排序",
      }),
      followup: { text: "帮我写一个快速排序", elapsedMs: 10_000 },
    }),
  },
  { id: "N12", build: () => ({ signal: mkSignal({ leaseEpochs: 2 }) }) },
  {
    id: "N13",
    build: () => ({ signal: mkSignal({}) }), // 审批被拒后正常结束 —— 无信号输入
  },
  {
    id: "N14",
    build: () => ({
      signal: mkSignal({
        status: "cancelled",
        stoppedByUser: true,
        durationMs: 30_000,
        toolFailures: 4,
      }),
    }),
  },
]

let fp = 0
let fn = 0
let tp = 0
let tn = 0

describe("应弹语料 P1–P8", () => {
  for (const { id, build } of POSITIVE) {
    test(id, () => {
      now = 0
      const { policy, drive } = harness()
      const { signal, followup } = build()
      let shown: boolean
      if (id === "P7") {
        // 先喂一个命中强抱怨的上一个 run（分数不足不弹，但种下标记）。
        drive(mkSignal(), { text: "还是不行", elapsedMs: 30_000 })
        shown = showAfter(policy, signal, followup)
      } else {
        shown = drive(signal, followup)
      }
      if (shown) tp += 1
      else fn += 1
      expect(shown).toBe(true)
    })
  }
})

describe("不弹语料 N1–N14", () => {
  for (const { id, build } of NEGATIVE) {
    test(id, () => {
      now = 0
      const { drive } = harness()
      const { signal, followup } = build()
      const shown = drive(signal, followup)
      if (shown) fp += 1
      else tn += 1
      expect(shown).toBe(false)
    })
  }
})

const EXTRA_NEGATIVES = 3 // N15/N16/N17 —— 需多条 followup / 前置 run，不进表

describe("不弹语料 N15–N16", () => {
  test("N15 仅「还是不行」+ 180s 内第二条无抱怨消息 → 不弹（score 保持 2）", () => {
    now = 0
    const { policy } = harness()
    const signal = mkSignal({ prompt: "帮我写一个快速排序" })
    policy.runTerminal(signal, now)
    now += 30_000
    expect(policy.followupSent("还是不行", now).kind).toBe("none") // score=2
    now += 40_000 // 仍 <180s 窗
    // 第二条消息不替换第一条，但会触发重评 —— 重评不得把本候选自己的
    // negative_followup 当“上一 run”自加 repeated_dissatisfaction。
    const ev = policy.followupSent("另外帮我看下部署脚本", now)
    expect(ev.kind).toBe("none")
    now += 200_000
    expect(policy.tick().kind).toBe("none")
    expect(policy.askedRunIds).not.toContain(signal.runId)
    tn += 1
  })

  test("N16 上一 run 无抱怨、本 run 后续「还是不行」→ 不弹", () => {
    now = 0
    const { policy, drive } = harness()
    drive(mkSignal()) // 上一个 run 干净结束，不种 negative 标记
    now += 60_000
    const shown = showAfter(
      policy,
      mkSignal({ prompt: "帮我写一个快速排序" }),
      { text: "还是不行", elapsedMs: 30_000 },
    )
    expect(shown).toBe(false)
    tn += 1
  })

  test("N17 分页历史 run 的抱怨（sentAt < terminalAt）不当后续消息 → 不弹", () => {
    now = 0
    const { policy } = harness()
    const signal = mkSignal({ prompt: "帮我写一个快速排序" })
    policy.runTerminal(signal, now)
    // 「加载更早」把历史 run 的抱怨带进来 —— sentAt 早于候选终态。
    expect(policy.followupSent("还是不行", now - 1_000).kind).toBe("none")
    now += 200_000
    policy.tick()
    // 历史消息不得记成 negative：下一 run +「还是不行」若被污染会
    // +1.5 repeated_dissatisfaction 变成弹出（同 N16 基线不弹）。
    const shown = showAfter(
      policy,
      mkSignal({ prompt: "再看一个" }),
      { text: "还是不行", elapsedMs: 30_000 },
    )
    expect(shown).toBe(false)
    tn += 1
  })
})

// ---- 门（G1–G9） ------------------------------------------------------------

describe("门", () => {
  test("G1 同一 run 只问一次", () => {
    now = 0
    const { policy, drive } = harness()
    const signal = mkSignal({ status: "failed" })
    expect(drive(signal)).toBe(true)
    advance(31 * 60_000) // 越过 30min 重显示间隔，只剩 run 级记忆
    expect(showAfter(policy, signal)).toBe(false)
    expect(policy.askedRunIds).toContain(signal.runId)
  })

  test("G2 30min 内第二个合格 run 不弹", () => {
    now = 0
    const { policy, drive } = harness()
    expect(drive(mkSignal({ status: "failed" }))).toBe(true)
    advance(5 * 60_000)
    expect(showAfter(policy, mkSignal({ status: "failed" }))).toBe(false)
  })

  test("G3 连续 2 次不需要 → 24h 冷却", () => {
    now = 0
    const { policy, drive } = harness()
    expect(drive(mkSignal({ status: "failed" }))).toBe(true)
    policy.dismissed("r1")
    advance(31 * 60_000)
    expect(drive(mkSignal({ status: "failed" }))).toBe(true)
    policy.dismissed("r2")
    // 第二次 dismiss → 24h 冷却
    advance(31 * 60_000)
    const third = mkSignal({ status: "failed" })
    expect(showAfter(policy, third)).toBe(false)
    advance(2 * 3600_000)
    expect(showAfter(policy, mkSignal({ status: "failed" }))).toBe(false)
    advance(23 * 3600_000) // 距冷却开始 ~25h
    expect(drive(mkSignal({ status: "failed" }))).toBe(true)
  })

  test("G4 同会话当天最多 2 次", () => {
    now = 0
    const { policy, drive } = harness()
    expect(drive(mkSignal({ status: "failed" }))).toBe(true)
    advance(31 * 60_000)
    expect(drive(mkSignal({ status: "failed" }))).toBe(true)
    advance(31 * 60_000)
    // 同会话第 3 个：30min 门已越过，只剩 session 日上限。
    expect(showAfter(policy, mkSignal({ status: "failed" }))).toBe(false)
  })

  test("G5 开关关闭不弹", () => {
    now = 0
    const { drive } = harness(gates({ enabled: false }))
    expect(drive(mkSignal({ status: "failed" }))).toBe(false)
  })

  test("G6 页面 hidden 不弹", () => {
    now = 0
    const { drive } = harness(gates({ visible: false }))
    expect(drive(mkSignal({ status: "failed" }))).toBe(false)
  })

  test("G7 composer 有内容 / 刚聚焦不弹", () => {
    now = 0
    const { drive: withText } = harness(gates({ composerEmpty: false }))
    expect(withText(mkSignal({ status: "failed" }))).toBe(false)
    const { drive: focused } = harness(gates({ composerFocusedWithinMs: 500 }))
    expect(focused(mkSignal({ status: "failed" }))).toBe(false)
  })

  test("G8 已有 Modal 打开不弹", () => {
    now = 0
    const { drive } = harness(gates({ modalOpen: true }))
    expect(drive(mkSignal({ status: "failed" }))).toBe(false)
  })

  test("G9 延迟期内开始输入 → 取消且不算问过", () => {
    now = 0
    const { policy } = harness()
    const signal = mkSignal({ status: "failed" })
    const event = policy.runTerminal(signal, now)
    expect(event.kind).toBe("scheduled")
    now += 800 // 未到 1500ms 延迟点
    const cancel = policy.composerActivity()
    expect(cancel.kind).toBe("cancelled")
    now += PROMPT_DELAY_MS + 5_000
    expect(policy.tick().kind).toBe("none")
    expect(policy.askedRunIds).not.toContain(signal.runId)
  })

  test("G10 会话 A 当天 2 次后切到 B 再问 1 次，回 A 仍不弹", () => {
    now = 0
    const { policy, drive } = harness()
    const inA = () => mkSignal({ status: "failed", sessionId: "sess-a" })
    const inB = () => mkSignal({ status: "failed", sessionId: "sess-b" })
    expect(drive(inA())).toBe(true)
    advance(31 * 60_000)
    expect(drive(inA())).toBe(true)
    advance(31 * 60_000)
    expect(drive(inB())).toBe(true) // B 的 1 次不得把 A 的计数清掉
    advance(31 * 60_000)
    expect(showAfter(policy, inA())).toBe(false)
    expect(policy.sessionDailyCount("sess-a")).toBe(2)
    expect(policy.sessionDailyCount("sess-b")).toBe(1)
  })

  test("G11 点「不需要」后的旧收尾不得影响之后的新候选", () => {
    now = 0
    const { policy, drive } = harness()
    expect(drive(mkSignal({ status: "failed" }))).toBe(true)
    policy.dismissed("r1") // 结束旧候选（提交其轨迹）
    advance(25_000) // 模拟旧 20s 自动收起计时器已过的时刻
    advance(31 * 60_000) // 越过 30min 重显示间隔
    const next = mkSignal({ status: "failed" })
    expect(drive(next)).toBe(true)
    expect(policy.askedRunIds).toContain(next.runId)
  })
})

test("混淆矩阵汇总", () => {
  console.log(
    `MATRIX should-show:${tp}/${POSITIVE.length} ` +
      `should-hide:${tn}/${NEGATIVE.length + EXTRA_NEGATIVES} FP=${fp} FN=${fn}`,
  )
  expect(fp).toBe(0)
  expect(fn).toBe(0)
})
