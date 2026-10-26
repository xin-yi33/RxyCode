// React 适配层 —— AutoPromptPolicy（纯模块，bun test 覆盖语料）+
// 真实时钟/localStorage/DOM 门探针。挂在 SessionPage：RunTimeline 上报
// 实时终态信号，SessionPage 上报新 run 的后续消息，卡片由本 hook 渲染。
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { useUi } from "../../state/ui"
import type { RunView } from "../runs/eventReducer"
import type { RunSummary } from "../../sdk/client"
import {
  AUTO_HIDE_MS,
  AutoPromptPolicy,
  autoPromptEnabled,
  loadAskedRuns,
  loadPromptState,
  STORAGE_ASKED,
  STORAGE_STATE,
  type PromptEvent,
  type RunTerminalSignal,
} from "./autoPrompt"

export type AutoPromptCardState = {
  runId: string
  sessionId: string
  reasons: string[]
}

// RunView → 打分输入。live = 组件挂载期间观察到 非终态→终态 的真实转换。
// stoppedByUser 由调用方从事件流判定（出现过 cancel_requested），
// 不能用终态 cancelled —— 系统取消（配额/超时）也会落到 cancelled。
export function signalFromRunView(
  run: RunSummary,
  view: RunView,
  stoppedByUser = false,
): RunTerminalSignal {
  let finalText = ""
  for (const item of view.timeline) {
    if (item.kind === "final") finalText = item.text
  }
  const toolFailures = view.timeline.filter(
    (item) =>
      item.kind === "tool" &&
      (item.status === "failed" ||
        (item.status === "completed" && (item.exitCode ?? 0) !== 0)),
  ).length
  const createdAt = run.created_at ? Date.parse(run.created_at) : 0
  return {
    runId: run.run_id,
    sessionId: "",
    status: view.status,
    finalText,
    toolFailures,
    stoppedByUser,
    durationMs: createdAt > 0 ? Math.max(0, Date.now() - createdAt) : 0,
    leaseEpochs: view.leaseEpochs.length,
    prompt: run.message,
    live: true, // 调用方只在观察到真实转换时才上报
  }
}

function composerFocusedMs(): number | null {
  const el = document.activeElement
  if (!el) return null
  if (el.closest?.('[data-testid="chat-composer"]')) return 0
  const last = composerFocusTracker.lastAt
  return last === 0 ? null : Date.now() - last
}

// 全局 focusin/focusout 追踪 composer 最近聚焦时间（G7 门）。
const composerFocusTracker = { lastAt: 0, installed: false }
function installFocusTracker() {
  if (composerFocusTracker.installed || typeof document === "undefined") return
  composerFocusTracker.installed = true
  document.addEventListener(
    "focusin",
    (event) => {
      const target = event.target as HTMLElement | null
      if (target?.closest?.('[data-testid="chat-composer"]')) {
        composerFocusTracker.lastAt = Date.now()
      }
    },
    true,
  )
}

function persistPolicy(policy: AutoPromptPolicy) {
  try {
    localStorage.setItem(STORAGE_ASKED, JSON.stringify(policy.askedRunIds))
    localStorage.setItem(STORAGE_STATE, JSON.stringify(policy.persisted))
  } catch {
    // storage 不可写（隐私模式等）—— 会话内仍工作。
  }
}

export function useAutoFeedbackPrompt(sessionId: string) {
  const [card, setCard] = useState<AutoPromptCardState | null>(null)
  const hideTimerRef = useRef(0)
  const scheduleTimerRef = useRef(0)

  const policy = useMemo(() => {
    installFocusTracker()
    return new AutoPromptPolicy(
      () => Date.now(),
      loadAskedRuns(localStorage),
      loadPromptState(localStorage),
      () => ({
        enabled: autoPromptEnabled(localStorage),
        visible: document.visibilityState === "visible",
        // 门判定时现读 store —— 不能捕获渲染期快照（草稿会过期）。
        composerEmpty: (useUi.getState().drafts[sessionId]?.text ?? "").trim() === "",
        composerFocusedWithinMs: composerFocusedMs(),
        modalOpen: Boolean(document.querySelector("dialog[open]")),
      }),
    )
  }, [sessionId])

  const dispatch = useCallback(
    (event: PromptEvent) => {
      if (event.kind === "scheduled") {
        if (scheduleTimerRef.current) window.clearTimeout(scheduleTimerRef.current)
        scheduleTimerRef.current = window.setTimeout(() => {
          scheduleTimerRef.current = 0
          dispatch(policy.tick())
          persistPolicy(policy)
        }, event.delayMs)
        return
      }
      if (event.kind === "cancelled") {
        if (scheduleTimerRef.current) {
          window.clearTimeout(scheduleTimerRef.current)
          scheduleTimerRef.current = 0
        }
        return
      }
      if (event.kind === "show") {
        setCard({ runId: event.runId, sessionId: event.sessionId, reasons: event.reasons })
        if (hideTimerRef.current) window.clearTimeout(hideTimerRef.current)
        hideTimerRef.current = window.setTimeout(() => {
          hideTimerRef.current = 0
          setCard(null)
          policy.ignored()
        }, AUTO_HIDE_MS)
      }
    },
    [policy],
  )

  // 定期 tick：补 180s 窗口到期清理（无事件时也能收尾）。
  useEffect(() => {
    const timer = window.setInterval(() => dispatch(policy.tick()), 5_000)
    return () => {
      window.clearInterval(timer)
      if (scheduleTimerRef.current) window.clearTimeout(scheduleTimerRef.current)
      if (hideTimerRef.current) window.clearTimeout(hideTimerRef.current)
    }
  }, [policy, dispatch])

  /** RunTimeline 观察到 非终态→终态 转换时调用。 */
  const observeTerminal = useCallback(
    (signal: RunTerminalSignal) => {
      signal.sessionId = sessionId
      dispatch(policy.runTerminal(signal, Date.now()))
    },
    [policy, sessionId, dispatch],
  )

  /** 新 run 出现 → 上一条用户消息可能补充后续信号。 */
  const observeFollowup = useCallback(
    (text: string, sentAtMs: number) => {
      dispatch(policy.followupSent(text, sentAtMs))
    },
    [policy, dispatch],
  )

  /** 延迟窗内用户开始输入（composer 出现首个字符）→ 取消且不算问过。 */
  const observeComposerActivity = useCallback(() => {
    dispatch(policy.composerActivity())
  }, [policy, dispatch])

  const clearHideTimer = useCallback(() => {
    if (hideTimerRef.current) {
      window.clearTimeout(hideTimerRef.current)
      hideTimerRef.current = 0
    }
  }, [])

  const dismiss = useCallback(() => {
    // policy 更新放在 setCard updater 外 —— StrictMode 双调用会让
    // 一次点击记两次 dismissStreak。
    if (card) policy.dismissed(card.runId)
    clearHideTimer() // 否则 20s 后的 ignored() 会清掉后来的新候选
    setCard(null)
    persistPolicy(policy)
  }, [card, policy, clearHideTimer])

  const respond = useCallback(() => {
    const current = card
    setCard(null)
    clearHideTimer()
    policy.responded()
    persistPolicy(policy)
    return current
  }, [card, policy, clearHideTimer])

  const disableAutoPrompt = useCallback(() => {
    try {
      localStorage.setItem("rxy.feedback.autoPrompt", "0")
    } catch {
      // 同 persistPolicy 的尽力而为语义。
    }
    clearHideTimer()
    setCard(null)
    policy.responded()
    persistPolicy(policy)
  }, [policy, clearHideTimer])

  return {
    card,
    observeTerminal,
    observeFollowup,
    observeComposerActivity,
    dismiss,
    respond,
    disableAutoPrompt,
  }
}
