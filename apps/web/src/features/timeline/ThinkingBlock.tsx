import { IconSpinner } from "../../components/icons"

// 「处理过程」进度块：只展示推理步数与进行中状态 —— 模型思维链文本
// 永不进入 props（eventReducer 只按事件计步），本组件没有任何可展开的
// 原文区域。安全契约：用户可见的是进度，不是 CoT。
export function ThinkingBlock({ steps, active }: { steps: number; active: boolean }) {
  return (
    <div
      data-thinking
      data-thinking-status={active ? "active" : "complete"}
      className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted"
    >
      {active ? (
        <>
          <IconSpinner size={11} className="rxy-pulse" />
          <span>正在处理…</span>
        </>
      ) : (
        <span>处理过程</span>
      )}
      {steps > 1 ? <span className="text-muted-ink">（{steps} 步）</span> : null}
    </div>
  )
}
