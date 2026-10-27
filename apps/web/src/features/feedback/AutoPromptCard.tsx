// 自动询问卡片 —— 右下角非阻塞小卡（移动端底部全宽），
// role=dialog aria-modal=false，20s 无操作自动收起。
import { useState } from "react"

import { REASON_TEXT } from "./autoPrompt"
import type { AutoPromptCardState } from "./useAutoFeedbackPrompt"

export function AutoPromptCard({
  card,
  onRespond,
  onDismiss,
  onNever,
}: {
  card: AutoPromptCardState
  onRespond: () => void
  onDismiss: () => void
  onNever: () => void
}) {
  const [never, setNever] = useState(false)
  const reasons = card.reasons
    .map((reason) => REASON_TEXT[reason])
    .filter(Boolean)
    .slice(0, 3)
  return (
    <div
      className="feedback-auto-prompt"
      role="dialog"
      aria-modal="false"
      aria-label="反馈询问"
      data-testid="feedback-auto-prompt"
    >
      <p style={{ margin: 0, fontSize: 14 }}>这次回答好像不太对，要反馈一下吗？</p>
      {reasons.length > 0 ? (
        <p className="reasons" aria-label="触发原因">
          {reasons.map((text) => (
            <span key={text} className="rxy-chip">
              {text}
            </span>
          ))}
        </p>
      ) : null}
      <div className="row">
        <button
          type="button"
          className="rxy-primary-btn"
          data-testid="feedback-auto-respond"
          onClick={() => {
            if (never) onNever()
            onRespond()
          }}
        >
          反馈
        </button>
        <button
          type="button"
          className="rxy-ghost-control rounded px-2 py-1 text-sm"
          data-testid="feedback-auto-dismiss"
          onClick={() => {
            if (never) onNever()
            else onDismiss()
          }}
        >
          不需要
        </button>
      </div>
      <label className="never">
        <input
          type="checkbox"
          checked={never}
          onChange={(event) => setNever(event.target.checked)}
          data-testid="feedback-auto-never"
        />
        不再自动询问
      </label>
    </div>
  )
}
