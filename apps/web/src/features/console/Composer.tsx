import { useState, type KeyboardEvent } from "react"
import { useNavigate } from "react-router"
import { useQueryClient } from "@tanstack/react-query"

import { IconSend } from "../../components/icons"
import { Button } from "../../components/ui/button"
import { ApiError, createClient, type RunAccepted } from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { useUi, type PermissionProfile } from "../../state/ui"

const api = createClient()

type ComposerProps = {
  // null = /app new-task flow (POST /tasks creates the session).
  sessionId: string | null
  onSubmitted?: (accepted: RunAccepted) => void
}

const PROFILES: { value: PermissionProfile; label: string; hint: string }[] = [
  { value: "confirm", label: "需要确认", hint: "执行有风险的工具前会先征求你的同意" },
  { value: "full", label: "完全自动", hint: "工具不经确认直接执行" },
]

export function Composer({ sessionId, onSubmitted }: ComposerProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const draftKey = sessionId ?? "__new__"
  const draft = useUi((state) => state.drafts[draftKey])
  const setDraft = useUi((state) => state.setDraft)
  const clearDraft = useUi((state) => state.clearDraft)
  const text = draft?.text ?? ""
  const requestId = draft?.requestId ?? ""
  const permission = draft?.permission ?? "confirm"
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

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
    if (busy || !message) return
    const rid = requestId || crypto.randomUUID()
    setDraft(draftKey, { text, requestId: rid, permission })
    setBusy(true)
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
      setBusy(false)
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
    <section className="border-t border-border bg-background px-4 py-3">
      <div className="mx-auto max-w-3xl">
        <textarea
          aria-label="消息"
          placeholder="描述要做的任务…"
          rows={3}
          className={
            "min-h-[84px] w-full resize-y rounded-lg border border-border " +
            "bg-card px-3 py-2 text-sm text-foreground outline-none " +
            "focus:border-muted"
          }
          value={text}
          disabled={busy}
          onChange={(event) => update(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <select
            aria-label="权限模式"
            title={PROFILES.find((item) => item.value === permission)?.hint}
            className={
              "rounded-md border border-border bg-card px-2 py-1.5 " +
              "text-xs text-foreground"
            }
            value={permission}
            disabled={busy}
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
          {error ? (
            <p role="alert" className="text-xs text-failure">
              {error}
            </p>
          ) : (
            <p className="text-xs text-muted">Enter 发送，Shift+Enter 换行</p>
          )}
          <div className="ml-auto">
            <Button
              type="button"
              size="sm"
              disabled={busy || !text.trim()}
              onClick={() => void submit()}
            >
              <IconSend size={14} />
              {busy ? "提交中…" : "发送"}
            </Button>
          </div>
        </div>
      </div>
    </section>
  )
}
