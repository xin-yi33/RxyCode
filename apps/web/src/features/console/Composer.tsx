import { useEffect, useRef, useState, type KeyboardEvent } from "react"
import { useNavigate } from "react-router"
import { useQueryClient } from "@tanstack/react-query"

import { IconSend, IconSpinner, IconStop } from "../../components/icons"
import { ApiError, createClient, type RunAccepted, type RunSummary } from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { useUi, type PermissionProfile } from "../../state/ui"
import { isActiveRunStatus } from "../runs/status"

const api = createClient()

type ComposerProps = {
  // null = /app new-task flow (POST /tasks creates the session).
  sessionId: string | null
  // 会话当前活跃 run —— 有则发送键变为方形停止键、输入框禁用。
  activeRun?: RunSummary | null
  onSubmitted?: (accepted: RunAccepted) => void
}

const PROFILES: { value: PermissionProfile; label: string; hint: string }[] = [
  { value: "confirm", label: "需要确认", hint: "执行有风险的工具前会先征求你的同意" },
  { value: "full", label: "完全自动", hint: "工具不经确认直接执行" },
]

export function Composer({ sessionId, activeRun, onSubmitted }: ComposerProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const draftKey = sessionId ?? "__new__"
  const draft = useUi((state) => state.drafts[draftKey])
  const setDraft = useUi((state) => state.setDraft)
  const clearDraft = useUi((state) => state.clearDraft)
  const text = draft?.text ?? ""
  const requestId = draft?.requestId ?? ""
  const permission = draft?.permission ?? "confirm"
  const [sending, setSending] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState("")
  const areaRef = useRef<HTMLTextAreaElement>(null)

  const active = activeRun != null && isActiveRunStatus(activeRun.status)

  // 自动增高（≤200px，超出内部滚动）；草稿清空时回到一行。
  useEffect(() => {
    const area = areaRef.current
    if (!area) return
    area.style.height = "auto"
    area.style.height = `${Math.min(area.scrollHeight, 200)}px`
  }, [text])

  const update = (nextText: string) => {
    setError("")
    setDraft(draftKey, {
      text: nextText,
      // Editing the text after a failed send invalidates the old request_id;
      // a fresh one is minted at the next send.
      requestId: nextText === text ? requestId : "",
      permission,
    })
  }

  const submit = async () => {
    const message = text.trim()
    if (sending || active || !message) return
    const rid = requestId || crypto.randomUUID()
    setDraft(draftKey, { text, requestId: rid, permission })
    setSending(true)
    setError("")
    try {
      const body = {
        message,
        request_id: rid,
        permission_profile: permission,
      }
      const accepted = sessionId
        ? await api.createRun(sessionId, body)
        : await api.createTask(body)
      clearDraft(draftKey)
      void queryClient.invalidateQueries({ queryKey: ["sessions"] })
      void queryClient.invalidateQueries({
        queryKey: ["sessionRuns", accepted.session_id],
      })
      void queryClient.invalidateQueries({
        queryKey: ["session", accepted.session_id],
      })
      if (onSubmitted) {
        onSubmitted(accepted)
      } else {
        navigate(`/app/s/${accepted.session_id}`)
      }
    } catch (err) {
      if (err instanceof ApiError) {
        // A real HTTP response arrived — the server has seen this request_id,
        // so a retry must use a new one.
        setDraft(draftKey, { text, requestId: "", permission })
        setError(apiErrorText(err))
      } else {
        // Network failure: keep the request_id so retry is idempotent.
        setError("无法连接服务器")
      }
    } finally {
      setSending(false)
    }
  }

  const cancel = async () => {
    if (!activeRun || !active || cancelling) return
    setCancelling(true)
    setError("")
    try {
      await api.cancelRun(activeRun.run_id)
      void queryClient.invalidateQueries({ queryKey: ["sessionRuns", sessionId] })
      void queryClient.invalidateQueries({ queryKey: ["sessions"] })
    } catch (err) {
      setError(apiErrorText(err))
    } finally {
      setCancelling(false)
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault()
      void submit()
    }
  }

  return (
    <div className="px-4 pb-4 pt-1">
      <div className="mx-auto max-w-3xl">
        <div
          className={
            "rounded-2xl border border-border bg-card transition-colors " +
            "focus-within:border-muted"
          }
        >
          <textarea
            ref={areaRef}
            aria-label="消息"
            placeholder={active ? "任务运行中…" : "描述要做的任务…"}
            rows={1}
            className={
              "block max-h-[200px] w-full resize-none bg-transparent px-4 pb-1 " +
              "pt-3 text-sm leading-relaxed outline-none"
            }
            value={text}
            disabled={sending || active}
            onChange={(event) => update(event.target.value)}
            onKeyDown={onKeyDown}
          />
          <div className="flex items-center gap-2 px-2 pb-2">
            <select
              aria-label="权限模式"
              title={PROFILES.find((item) => item.value === permission)?.hint}
              className={
                "rounded-full border border-border bg-transparent px-3 py-1.5 " +
                "text-xs text-muted-ink outline-none"
              }
              value={permission}
              disabled={sending || active}
              onChange={(event) =>
                setDraft(draftKey, {
                  text,
                  requestId,
                  permission: event.target.value as PermissionProfile,
                })
              }
            >
              {PROFILES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <div className="ml-auto">
              {active ? (
                <button
                  type="button"
                  aria-label={cancelling ? "取消中…" : "停止"}
                  title={cancelling ? "取消中…" : "停止"}
                  disabled={cancelling}
                  onClick={() => void cancel()}
                  className={
                    "flex h-9 w-9 items-center justify-center rounded-full " +
                    "bg-foreground text-background disabled:opacity-50"
                  }
                >
                  {cancelling ? (
                    <IconSpinner size={15} />
                  ) : (
                    <IconStop size={15} />
                  )}
                </button>
              ) : (
                <button
                  type="button"
                  aria-label={sending ? "提交中…" : "发送"}
                  title={sending ? "提交中…" : "发送"}
                  disabled={sending || !text.trim()}
                  onClick={() => void submit()}
                  className={
                    "flex h-9 w-9 items-center justify-center rounded-full " +
                    "bg-foreground text-background disabled:opacity-50"
                  }
                >
                  {sending ? (
                    <IconSpinner size={15} />
                  ) : (
                    <IconSend size={15} />
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
        {error ? (
          <p role="alert" className="mt-2 text-xs text-failure">
            {error}
          </p>
        ) : (
          <p className="mt-2 px-1 text-xs text-muted">
            Enter 发送，Shift+Enter 换行
          </p>
        )}
      </div>
    </div>
  )
}
