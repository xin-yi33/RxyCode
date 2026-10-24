import {
  useEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type DragEvent,
  type KeyboardEvent,
} from "react"
import { Link, useLocation, useNavigate } from "react-router"
import { useQueryClient } from "@tanstack/react-query"

import { IconClose, IconSend, IconSpinner, IconStop } from "../../components/icons"
import { FileName } from "../../components/FileName"
import { Button } from "../../components/ui/button"
import {
  ApiError,
  createClient,
  type Attachment,
  type RunAccepted,
  type RunSummary,
} from "../../sdk/client"
import { apiErrorText, isUnauthorized } from "../../sdk/errors"
import { useUi, type PermissionProfile } from "../../state/ui"
import { createSecureRequestId } from "../../lib/secureRequestId"
import { LoginPrompt } from "../auth/LoginPrompt"
import { useAuth } from "../auth/useAuth"
import { useModelsCatalog } from "../models/queries"
import { isActiveRunStatus } from "../runs/status"
import { ModelPicker } from "./ModelPicker"

const api = createClient()

// UI-03：compositionend 之后这段时间内的 Enter 仍可能来自一次输入法确认。
const IME_ENTER_GRACE_MS = 500

type ComposerProps = {
  // null = /app new-task flow (POST /tasks creates the session).
  sessionId: string | null
  // 会话当前活跃 run —— 有则发送键变为方形停止键、输入框禁用。
  activeRun?: RunSummary | null
  onSubmitted?: (accepted: RunAccepted) => void
}

const PROFILES: { value: PermissionProfile; label: string; hint: string }[] = [
  { value: "confirm", label: "需要确认", hint: "执行有风险的工具前会先征求你的同意" },
  {
    value: "auto_edit",
    label: "自动编辑",
    hint: "写代码不再询问，其它有风险操作仍需确认",
  },
  { value: "full", label: "完全自动", hint: "工具不经确认直接执行" },
]

// 一张附件卡：本地 File 句柄 + 服务端暂存行。File 对象不可序列化，
// 不随草稿持久化 —— 刷新后卡片消失是诚实的（文件句柄已失效）。
type PendingFile = {
  localId: string
  file: File
  attachment: Attachment | null
  progress: number // 0..1 上传环
  error: string
  controller: AbortController
}

let pendingSeq = 0
const nextLocalId = () => `pf-${++pendingSeq}`

function formatBytes(size: number): string {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)}MB`
  if (size >= 1024) return `${Math.ceil(size / 1024)}KB`
  return `${size}B`
}

export function Composer({ sessionId, activeRun, onSubmitted }: ComposerProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const draftKey = sessionId ?? "__new__"
  const draft = useUi((state) => state.drafts[draftKey])
  const patchDraft = useUi((state) => state.patchDraft)
  const clearDraft = useUi((state) => state.clearDraft)
  const inheritModelRefIfUnset = useUi((state) => state.inheritModelRefIfUnset)
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
  const effectiveCatalogModel = catalog.data?.models.find(
    (model) => model.model_ref === effectiveModelRef,
  )
  const modelNeedsReselection =
    effectiveModelRef != null &&
    (effectiveCatalogModel?.source === "platform" || !effectiveCatalogModel)
  const [sending, setSending] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [files, setFiles] = useState<PendingFile[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [error, setError] = useState("")
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [errorModelRef, setErrorModelRef] = useState<string | null>(null)
  const [errorLink, setErrorLink] = useState<{ to: string; label: string } | null>(null)
  // "send" | "model" —— 同一个登录提示层，措辞随触发点不同。
  const [loginPrompt, setLoginPrompt] = useState<"send" | "model" | null>(null)
  // 模型切换提示（对齐 CLI）：换模型后输入框上方挂一行，约 4s 自动消失。
  const [modelHint, setModelHint] = useState("")
  const modelHintTimer = useRef(0)
  const areaRef = useRef<HTMLTextAreaElement>(null)
  // UI-03：输入法（中文/日文等组合输入）守卫。
  // composition 期间的 Enter 是“确认候选”，不是发送；部分输入法会在
  // compositionend 之后才补发这次 Enter，所以再留一个 500ms 宽限窗口。
  const composingRef = useRef(false)
  const compositionEndedAt = useRef(Number.NEGATIVE_INFINITY)
  // 一次合法发送只允许一个任务请求：React 的 sending state 要到下一次渲染
  // 才生效，同一个 task 里连发的第二个 Enter/点击仍会看到 sending=false。
  // 同步 ref 在 submit() 入口、任何 await 之前占位，请求结算后释放。
  const submitInFlightRef = useRef(false)

  const showModelHint = (label: string) => {
    if (errorCode === "BYOK_REQUIRED" && errorModelRef == null) {
      setError("")
      setErrorLink(null)
      setErrorCode(null)
      setErrorModelRef(null)
    }
    setModelHint(`已切换模型为 ${label}，下次任务生效`)
    window.clearTimeout(modelHintTimer.current)
    modelHintTimer.current = window.setTimeout(() => setModelHint(""), 4000)
  }
  useEffect(
    () => () => window.clearTimeout(modelHintTimer.current),
    [],
  )

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

  const fail = (
    message: string,
    link: { to: string; label: string } | null = null,
    code: string | null = null,
    failedModelRef: string | null = null,
  ) => {
    setError(message)
    setErrorLink(link)
    setErrorCode(code)
    setErrorModelRef(failedModelRef)
  }

  // ---- 附件（API-FILE-*）：卡片先在本地出现，暂存/上传/绑定的每一步都可观测。
  const webCaps = auth.me?.web_capabilities
  const attachmentsEnabled = webCaps?.attachments !== false
  const maxBytes = webCaps?.attachment_max_bytes ?? 100 * 1024 * 1024
  const maxPerRun = webCaps?.attachment_max_per_run ?? 10
  const uploadsBusy = files.some((f) => !f.attachment || f.attachment.state !== "ready")
  const readyIds = files
    .filter((f) => f.attachment?.state === "ready")
    .map((f) => f.attachment!.attachment_id)

  const patchFile = (localId: string, patch: Partial<PendingFile>) => {
    setFiles((prev) => prev.map((f) => (f.localId === localId ? { ...f, ...patch } : f)))
  }

  const startUpload = async (entry: PendingFile) => {
    try {
      const created = await api.createAttachment({
        filename: entry.file.name,
        content_type: entry.file.type || "application/octet-stream",
        size_bytes: entry.file.size,
        session_id: sessionId,
      })
      patchFile(entry.localId, { attachment: created, error: "" })
      const done = await api.uploadAttachmentContent(
        created.attachment_id,
        entry.file,
        (received, total) => patchFile(entry.localId, { progress: total ? received / total : 0 }),
        entry.controller.signal,
      )
      patchFile(entry.localId, { attachment: done, progress: 1 })
    } catch (err) {
      if (err instanceof ApiError && err.code === "ABORTED") return
      patchFile(entry.localId, {
        error: err instanceof ApiError ? err.code : "上传失败",
      })
    }
  }

  const addFiles = (list: FileList | File[]) => {
    setError("")
    for (const file of Array.from(list)) {
      if (files.length >= maxPerRun) {
        fail(`一次任务最多 ${maxPerRun} 个附件`)
        return
      }
      if (file.size > maxBytes) {
        fail(`「${file.name}」超过 ${formatBytes(maxBytes)} 上限`)
        continue
      }
      const entry: PendingFile = {
        localId: nextLocalId(),
        file,
        attachment: null,
        progress: 0,
        error: "",
        controller: new AbortController(),
      }
      setFiles((prev) => [...prev, entry])
      void startUpload(entry)
    }
  }

  const removeFile = (entry: PendingFile) => {
    entry.controller.abort()
    setFiles((prev) => prev.filter((f) => f.localId !== entry.localId))
    if (entry.attachment?.attachment_id) {
      void api.deleteAttachment(entry.attachment.attachment_id).catch(() => undefined)
    }
  }

  const retryFile = (entry: PendingFile) => {
    // 失败行在服务端已是终态 —— 重新建一张暂存行，不留孤儿。
    if (entry.attachment?.attachment_id) {
      void api.deleteAttachment(entry.attachment.attachment_id).catch(() => undefined)
    }
    const controller = new AbortController()
    patchFile(entry.localId, {
      error: "",
      progress: 0,
      attachment: null,
      controller,
    })
    void startUpload({ ...entry, attachment: null, error: "", progress: 0, controller })
  }

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const pasted = event.clipboardData?.files
    if (pasted && pasted.length) {
      event.preventDefault()
      addFiles(pasted)
    }
  }

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    if (event.dataTransfer?.files?.length) {
      event.preventDefault()
      addFiles(event.dataTransfer.files)
    }
  }

  const update = (nextText: string) => {
    setError("")
    setErrorLink(null)
    setErrorCode(null)
    setErrorModelRef(null)
    patchDraft(draftKey, {
      text: nextText,
      // Editing the text after a failed send invalidates the old request_id;
      // a fresh one is minted at the next send.
      requestId: nextText === text ? requestId : "",
    })
  }

  const submitOnce = async () => {
    const message = text.trim()
    if (sending || active || !message) return
    if (files.length > 0 && uploadsBusy) {
      const failed = files.find((f) => f.error)
      fail(failed ? "附件上传失败：请重试或移除后发送" : "附件还在上传，就绪后才能发送")
      return
    }
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
    if (modelNeedsReselection) {
      fail("当前模型已停止提供，请配置或重新选择自有模型", {
        to: "/app/settings?section=models",
        label: "管理模型",
      })
      return
    }
    let rid = requestId
    if (!rid) {
      try {
        rid = createSecureRequestId()
      } catch {
        fail("无法安全创建请求标识，请更新浏览器后重试")
        return
      }
    }
    patchDraft(draftKey, { text, requestId: rid })
    setSending(true)
    setError("")
    setErrorLink(null)
    setErrorCode(null)
    setErrorModelRef(null)
    try {
      const body = {
        message,
        request_id: rid,
        permission_profile: permission,
        model_ref: effectiveModelRef,
        attachment_ids: readyIds.length ? readyIds : undefined,
      }
      const accepted = sessionId
        ? await api.createRun(sessionId, body)
        : await api.createTask(body)
      if (!sessionId && typeof effectiveModelRef === "string" && effectiveModelRef.length > 0) {
        inheritModelRefIfUnset(accepted.session_id, effectiveModelRef)
      }
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
          }, err.code, effectiveModelRef)
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

  // UI-03「一次合法发送只产生一个任务请求」：同一 tick 里第二个 Enter/点击在
  // React 刷新 sending 之前仍会进入 submit，重复 mint request_id 并重复 POST。
  // 这里在任何 await 之前同步占位；成功/失败/校验早退后都在 finally 释放，
  // 不会阻塞下一次正常发送。submitOnce() 的语义保持原样。
  const submit = async () => {
    if (submitInFlightRef.current) return
    submitInFlightRef.current = true
    try {
      await submitOnce()
    } finally {
      submitInFlightRef.current = false
    }
  }

  const cancel = async () => {
    if (!activeRun || !active || cancelling) return
    setCancelling(true)
    setError("")
    setErrorLink(null)
    setErrorCode(null)
    setErrorModelRef(null)
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

  const onCompositionStart = () => {
    composingRef.current = true
  }

  const onCompositionEnd = () => {
    composingRef.current = false
    compositionEndedAt.current = Date.now()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // 只有不带 Shift 的 Enter 才可能是发送；Shift+Enter 保持换行。
    if (event.key !== "Enter" || event.shiftKey) return
    const native = event.nativeEvent
    // 组合态（isComposing / 229）交给输入法，不 preventDefault，否则会吞掉
    // 候选确认。
    if (
      composingRef.current ||
      native.isComposing ||
      event.keyCode === 229 ||
      native.keyCode === 229
    ) {
      return
    }
    // compositionend 后 <500ms 的 Enter 仍可能属于同一次输入法确认。
    if (Date.now() - compositionEndedAt.current < IME_ENTER_GRACE_MS) return
    // 长按重复派发的 Enter 只发送一次。
    if (event.repeat) return
    // 模态层开着时全局发送让位。
    if (document.querySelector("dialog[open]")) return
    event.preventDefault()
    void submit()
  }

  return (
    <div className="rxy-composer-dock px-4 pb-4 pt-1">
      <div className="mx-auto max-w-3xl">
        {showPendingBanner ? (
          <p className="mb-2 flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-ink">
            <span className="rxy-weight-medium min-w-0 flex-1">草稿已保留，确认后发送</span>
            <button
              type="button"
              aria-label="关闭提示"
              title="关闭提示"
              className="rxy-ghost-control shrink-0 rounded p-0.5 text-muted"
              onClick={() => setPendingIntent(false)}
            >
              <IconClose size={12} className="rxy-icon-inline" />
            </button>
          </p>
        ) : null}
        {modelHint ? (
          <p role="status" data-model-hint className="mb-2 px-1 text-xs text-muted-ink">
            {modelHint}
          </p>
        ) : null}
        <div
          data-testid="chat-composer"
          className="rxy-composer-shell rounded-2xl bg-card transition-colors"
          onDrop={attachmentsEnabled ? onDrop : undefined}
          onDragOver={attachmentsEnabled ? (event) => event.preventDefault() : undefined}
        >
          {files.length > 0 ? (
            <ul data-attachments className="flex flex-wrap gap-2 px-3 pt-3">
              {files.map((entry) => {
                const state = entry.attachment?.state
                const uploading = !entry.error && state !== "ready"
                return (
                  <li
                    key={entry.localId}
                    className={
                      "rxy-nested-card flex items-center gap-2 bg-sidebar px-2.5 py-1.5 text-xs"
                    }
                    title={entry.attachment?.reason ?? undefined}
                  >
                    <FileName name={entry.file.name} className="rxy-weight-medium max-w-40" />
                    <span className="rxy-tabular-nums text-muted">
                      {formatBytes(entry.file.size)}
                    </span>
                    {entry.error ? (
                      <>
                        <span className="rxy-weight-medium text-failure">失败</span>
                        <button
                          type="button"
                          className="rxy-ghost-control rxy-weight-medium rounded px-1 text-muted-ink underline"
                          onClick={() => retryFile(entry)}
                        >
                          重试
                        </button>
                      </>
                    ) : uploading ? (
                      <span className="rxy-tabular-nums text-muted-ink" aria-live="polite">
                        {Math.round(entry.progress * 100)}%
                      </span>
                    ) : (
                      <span className="rxy-weight-medium text-success">就绪</span>
                    )}
                    <button
                      type="button"
                      aria-label={`移除 ${entry.file.name}`}
                      title="移除"
                      className="rxy-ghost-control rounded p-0.5 text-muted"
                      onClick={() => removeFile(entry)}
                    >
                      <IconClose size={10} className="rxy-icon-inline" />
                    </button>
                  </li>
                )
              })}
            </ul>
          ) : null}
          <textarea
            ref={areaRef}
            aria-label="消息"
            placeholder={active ? "任务运行中…" : "描述要做的任务…"}
            rows={1}
            className={
              "rxy-composer-input rxy-weight-body block max-h-[200px] w-full resize-none " +
              "bg-transparent px-4 pb-1 pt-3 text-sm leading-relaxed outline-none"
            }
            value={text}
            disabled={sending || active}
            onChange={(event) => update(event.target.value)}
            onKeyDown={onKeyDown}
            onCompositionStart={onCompositionStart}
            onCompositionEnd={onCompositionEnd}
            onPaste={attachmentsEnabled ? onPaste : undefined}
          />
          <div className="flex flex-wrap items-center gap-2 px-2 pb-2">
            <select
              aria-label="权限模式"
              title={PROFILES.find((item) => item.value === permission)?.hint}
              className={
                "rxy-ghost-control rxy-weight-medium rounded-full px-3 py-1.5 " +
                "text-xs text-muted-ink"
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
            {attachmentsEnabled ? (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  className="hidden"
                  aria-label="选择附件"
                  onChange={(event) => {
                    if (event.target.files?.length) addFiles(event.target.files)
                    event.target.value = ""
                  }}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label="添加附件"
                  title="添加附件（也可以粘贴或拖入文件）"
                  disabled={sending || active}
                  onClick={() => fileInputRef.current?.click()}
                  className="rxy-weight-medium rounded-full px-3 py-1.5 text-xs disabled:opacity-50"
                >
                  附件
                </Button>
              </>
            ) : null}
            <div className="ml-auto flex items-center gap-2">
              <ModelPicker
                draftKey={draftKey}
                catalog={catalog}
                authStatus={auth.status}
                disabled={sending || active}
                disabledReason={active ? "运行中不可更换模型" : "提交中…"}
                onGuest={() => setLoginPrompt("model")}
                onSwitched={showModelHint}
                returnFocusRef={areaRef}
              />
              {active ? (
                <Button
                  size="icon"
                  aria-label={cancelling ? "取消中…" : "停止"}
                  title={cancelling ? "取消中…" : "停止"}
                  disabled={cancelling}
                  onClick={() => void cancel()}
                  className="rounded-full disabled:opacity-50"
                >
                  {cancelling ? (
                    <IconSpinner size={15} className="rxy-icon-inline" />
                  ) : (
                    <IconStop size={15} className="rxy-icon-inline" />
                  )}
                </Button>
              ) : (
                <Button
                  size="icon"
                  aria-label={sending ? "提交中…" : "发送"}
                  title={sending ? "提交中…" : "发送"}
                  disabled={sending || !text.trim()}
                  onClick={() => void submit()}
                  className="rounded-full disabled:opacity-50"
                >
                  {sending ? (
                    <IconSpinner size={15} className="rxy-icon-inline" />
                  ) : (
                    <IconSend size={15} className="rxy-icon-inline" />
                  )}
                </Button>
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
          <p className="rxy-weight-body mt-2 px-1 text-xs text-muted">
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
