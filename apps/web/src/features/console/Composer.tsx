import { useEffect, useRef, useState, type KeyboardEvent } from "react"
import { Link, useLocation, useNavigate } from "react-router"
import { useQueryClient } from "@tanstack/react-query"

import { IconClose, IconSend, IconSpinner, IconStop } from "../../components/icons"
import { ApiError, createClient, type RunAccepted, type RunSummary } from "../../sdk/client"
import { apiErrorText, isUnauthorized } from "../../sdk/errors"
import { useUi, type PermissionProfile } from "../../state/ui"
import { LoginPrompt } from "../auth/LoginPrompt"
import { useAuth } from "../auth/useAuth"
import { useModelsCatalog } from "../models/queries"
import { isActiveRunStatus } from "../runs/status"
import { ModelPicker } from "./ModelPicker"

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
  const location = useLocation()
  const queryClient = useQueryClient()
  const draftKey = sessionId ?? "__new__"
  const draft = useUi((state) => state.drafts[draftKey])
  const patchDraft = useUi((state) => state.patchDraft)
  const clearDraft = useUi((state) => state.clearDraft)
  const pendingIntent = useUi((state) => state.pendingIntent)
  const setPendingIntent = useUi((state) => state.setPendingIntent)
  const auth = useAuth()
  const authed = auth.status === "authed"
  const catalog = useModelsCatalog(authed)
  const text = draft?.text ?? ""
  const requestId = draft?.requestId ?? ""
  const permission = draft?.permission ?? "confirm"
  // undefined = 跟随服务端 default_model_ref；目录未加载时回退 null（默认链）。
  const modelRef = draft?.modelRef
  const effectiveModelRef =
    modelRef !== undefined ? modelRef : (catalog.data?.default_model_ref ?? null)
  const [sending, setSending] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState("")
  const [errorLink, setErrorLink] = useState<{ to: string; label: string } | null>(null)
  // "send" | "model" —— 同一个登录提示层，措辞随触发点不同。
  const [loginPrompt, setLoginPrompt] = useState<"send" | "model" | null>(null)
  const areaRef = useRef<HTMLTextAreaElement>(null)

  const active = activeRun != null && isActiveRunStatus(activeRun.status)
  const showPendingBanner = pendingIntent && authed

  // 登录流程中止（仍是访客）→ 清掉标记，不残留误导提示。
  useEffect(() => {
    if (pendingIntent && auth.status === "guest" && !auth.unavailable) {
      setPendingIntent(false)
    }
  }, [pendingIntent, auth.status, auth.unavailable, setPendingIntent])

  // 自动增高（≤200px，超出内部滚动）；草稿清空时回到一行。
  useEffect(() => {
    const area = areaRef.current
    if (!area) return
    area.style.height = "auto"
    area.style.height = `${Math.min(area.scrollHeight, 200)}px`
  }, [text])

  const fail = (message: string, link: { to: string; label: string } | null = null) => {
    setError(message)
    setErrorLink(link)
  }

  const update = (nextText: string) => {
    setError("")
    setErrorLink(null)
    patchDraft(draftKey, {
      text: nextText,
      // Editing the text after a failed send invalidates the old request_id;
      // a fresh one is minted at the next send.
      requestId: nextText === text ? requestId : "",
    })
  }

  const submit = async () => {
    const message = text.trim()
    if (sending || active || !message) return
    if (auth.status === "pending") {
      fail("正在确认登录状态，请稍候…")
      return
    }
    if (auth.status === "guest") {
      // 访客 → 不创建 run，弹登录提示层（PRD §3.2 动作级鉴权）。
      if (auth.unavailable) {
        fail("无法确认登录状态，请稍后重试")
        return
      }
      setLoginPrompt("send")
      return
    }
    const rid = requestId || crypto.randomUUID()
    patchDraft(draftKey, { text, requestId: rid })
    setSending(true)
    setError("")
    setErrorLink(null)
    try {
      const body = {
        message,
        request_id: rid,
        permission_profile: permission,
        model_ref: effectiveModelRef,
      }
      const accepted = sessionId
        ? await api.createRun(sessionId, body)
        : await api.createTask(body)
      clearDraft(draftKey)
      setPendingIntent(false)
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
        patchDraft(draftKey, { text, requestId: "" })
        if (isUnauthorized(err)) {
          // 会话中途失效：就地登录提示，SPA 跳转保住草稿。
          setLoginPrompt("send")
          return
        }
        if (err.code === "BYOK_REQUIRED") {
          // MOD-24：发送前未配置 → 引导到设置模型分区，草稿保留。
          fail(apiErrorText(err), {
            to: "/app/settings?section=models",
            label: "去添加 API Key",
          })
          return
        }
        fail(apiErrorText(err))
      } else {
        // Network failure: keep the request_id so retry is idempotent.
        fail("无法连接服务器")
      }
    } finally {
      setSending(false)
    }
  }

  const cancel = async () => {
    if (!activeRun || !active || cancelling) return
    setCancelling(true)
    setError("")
    setErrorLink(null)
    try {
      await api.cancelRun(activeRun.run_id)
      void queryClient.invalidateQueries({ queryKey: ["sessionRuns", sessionId] })
      void queryClient.invalidateQueries({ queryKey: ["sessions"] })
    } catch (err) {
      fail(apiErrorText(err))
    } finally {
      setCancelling(false)
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing && // 中文输入法候选态不发送
      !document.querySelector("dialog[open]") // 模态层开着时全局发送让位
    ) {
      event.preventDefault()
      void submit()
    }
  }

  return (
    <div className="px-4 pb-4 pt-1">
      <div className="mx-auto max-w-3xl">
        {showPendingBanner ? (
          <p className="mb-2 flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-ink">
            <span className="min-w-0 flex-1">草稿已保留，确认后发送</span>
            <button
              type="button"
              aria-label="关闭提示"
              title="关闭提示"
              className="shrink-0 rounded p-0.5 text-muted hover:bg-sidebar"
              onClick={() => setPendingIntent(false)}
            >
              <IconClose size={12} />
            </button>
          </p>
        ) : null}
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
                patchDraft(draftKey, {
                  permission: event.target.value as PermissionProfile,
                  // 权限属于幂等范围 —— 切换即重置 request_id。
                  requestId: "",
                })
              }
            >
              {PROFILES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <div className="ml-auto flex items-center gap-2">
              <ModelPicker
                draftKey={draftKey}
                catalog={catalog}
                authStatus={auth.status}
                disabled={sending || active}
                disabledReason={active ? "运行中不可更换模型" : "提交中…"}
                onGuest={() => setLoginPrompt("model")}
                returnFocusRef={areaRef}
              />
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
            {errorLink ? (
              <>
                {" "}
                <Link
                  className="underline"
                  to={errorLink.to}
                  state={{ from: location.pathname + location.search }}
                >
                  {errorLink.label}
                </Link>
              </>
            ) : null}
          </p>
        ) : (
          <p className="mt-2 px-1 text-xs text-muted">
            Enter 发送，Shift+Enter 换行
          </p>
        )}
      </div>
      {loginPrompt ? (
        <LoginPrompt
          title={loginPrompt === "model" ? "选择模型需要登录" : "发送任务需要登录"}
          onClose={() => setLoginPrompt(null)}
        />
      ) : null}
    </div>
  )
}
