// 共享反馈表单 —— 设置页「反馈」tab 与会话页「反馈此回答」Modal 共用。
// UI-01/02 规范：单层外壳（border:0 + inset 环）、内部 ghost、
// .rxy-tabular-nums 计数、Enter 不提交（textarea + IME 安全）、
// honeypot 隐藏字段 name=website。
import { useEffect, useRef, useState, type ChangeEvent, type DragEvent, type ClipboardEvent } from "react"
import { useUi } from "../../state/ui"
import { apiErrorText, errorWithCode } from "../../sdk/errors"
import { ApiError, createClient, type FeedbackItem } from "../../sdk/client"
import { AltchaWidget } from "../auth/AltchaWidget"

const api = createClient()

export type FeedbackPrefill = {
  kind?: string
  module?: string
  severity?: string
  title?: string
  body?: string
  run_id?: string
  session_id?: string
  source?: string
  trigger_reasons?: string[]
}

type PendingImage = {
  localId: string
  file: File
  imageId: string | null
  progress: number
  error: string | null
  previewUrl: string
}

const KINDS = [
  { id: "bug", label: "Bug" },
  { id: "suggestion", label: "优化建议" },
  { id: "content_quality", label: "内容质量" },
] as const

const MODULES = [
  { id: "chat", label: "聊天 / 会话" },
  { id: "run_output", label: "回答内容" },
  { id: "tools", label: "工具执行" },
  { id: "files_preview", label: "文件 / 预览" },
  { id: "settings", label: "设置" },
  { id: "auth", label: "登录 / 账户" },
  { id: "models_byok", label: "模型 / API Key" },
  { id: "mobile", label: "移动端" },
  { id: "performance", label: "性能" },
  { id: "other", label: "其他" },
] as const

const SEVERITIES = [
  { id: "low", label: "低" },
  { id: "normal", label: "中" },
  { id: "high", label: "高" },
] as const

const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"])
const IMAGE_MAX_BYTES = 5 * 1024 * 1024
const IMAGE_MAX_COUNT = 5
const BODY_MAX = 5000

export default function FeedbackForm({
  prefill,
  onSubmitted,
  onClose,
}: {
  prefill?: FeedbackPrefill
  onSubmitted?: (item: FeedbackItem) => void
  onClose?: () => void
}) {
  const showToast = useUi((s) => s.showToast)
  const [kind, setKind] = useState<string>(prefill?.kind ?? "bug")
  const [module, setModule] = useState<string>(prefill?.module ?? "chat")
  const [severity, setSeverity] = useState<string>(prefill?.severity ?? "normal")
  const [title, setTitle] = useState(prefill?.title ?? "")
  const [body, setBody] = useState(prefill?.body ?? "")
  const [images, setImages] = useState<PendingImage[]>([])
  const [website, setWebsite] = useState("") // honeypot
  const [captcha, setCaptcha] = useState("")
  const [captchaNeeded, setCaptchaNeeded] = useState(false)
  const [error, setError] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const requestRef = useRef<string>("")
  const draftRef = useRef<string>("")
  const fileInputRef = useRef<HTMLInputElement>(null)
  const imagesRef = useRef<PendingImage[]>(images)
  imagesRef.current = images

  useEffect(() => {
    const list = imagesRef.current
    return () => {
      for (const img of list) URL.revokeObjectURL(img.previewUrl)
    }
  }, [])

  const pageContext = () => ({
    page_path: window.location.pathname + window.location.search,
    client_build: "",
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    locale: navigator.language,
  })

  const addImages = (files: FileList | File[]) => {
    const next = [...images]
    for (const file of Array.from(files)) {
      if (next.length >= IMAGE_MAX_COUNT) break
      if (!IMAGE_TYPES.has(file.type)) {
        setError("只支持 PNG / JPEG / WebP 图片")
        continue
      }
      if (file.size > IMAGE_MAX_BYTES) {
        setError("图片不能超过 5MB")
        continue
      }
      const pending: PendingImage = {
        localId: crypto.randomUUID(),
        file,
        imageId: null,
        progress: 0,
        error: null,
        previewUrl: URL.createObjectURL(file),
      }
      next.push(pending)
      void startImageUpload(pending.localId, file)
    }
    setImages(next)
  }

  const startImageUpload = async (localId: string, file: File) => {
    try {
      const result = await api.uploadFeedbackImage(file, (received, total) => {
        setImages((list) =>
          list.map((img) =>
            img.localId === localId
              ? { ...img, progress: total > 0 ? Math.round((received / total) * 100) : 0 }
              : img,
          ),
        )
      })
      setImages((list) =>
        list.map((img) =>
          img.localId === localId ? { ...img, imageId: result.image_id, progress: 100 } : img,
        ),
      )
    } catch (err) {
      setImages((list) =>
        list.map((img) =>
          img.localId === localId ? { ...img, error: apiErrorText(err) } : img,
        ),
      )
    }
  }

  const removeImage = (localId: string) => {
    const target = images.find((img) => img.localId === localId)
    setImages((list) => list.filter((img) => img.localId !== localId))
    if (target) {
      URL.revokeObjectURL(target.previewUrl)
      if (target.imageId) void api.deleteFeedbackImage(target.imageId).catch(() => undefined)
    }
  }

  const retryImage = (localId: string) => {
    const target = images.find((img) => img.localId === localId)
    if (!target) return
    setImages((list) =>
      list.map((img) => (img.localId === localId ? { ...img, error: null, progress: 0 } : img)),
    )
    void startImageUpload(localId, target.file)
  }

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    if (event.dataTransfer.files.length) addImages(event.dataTransfer.files)
  }

  const onPaste = (event: ClipboardEvent) => {
    const files = Array.from(event.clipboardData.files).filter((f) =>
      f.type.startsWith("image/"),
    )
    if (files.length) {
      event.preventDefault()
      addImages(files)
    }
  }

  const uploading = images.some((img) => img.imageId === null && img.error === null)

  const submit = async () => {
    if (submitting) return
    const trimmedTitle = title.trim()
    const trimmedBody = body.trim()
    if (!trimmedTitle || trimmedBody.length < 10) {
      setError("请填写标题，描述至少 10 个字")
      return
    }
    setError("")
    setSubmitting(true)
    const draftKey = `${trimmedTitle}|${trimmedBody}`
    if (!requestRef.current || draftRef.current !== draftKey) {
      requestRef.current = crypto.randomUUID()
      draftRef.current = draftKey
    }
    try {
      const item = await api.submitFeedback({
        request_id: requestRef.current,
        kind,
        module,
        ...(kind === "bug" ? { severity } : {}),
        title: trimmedTitle,
        body: trimmedBody,
        image_ids: images.filter((img) => img.imageId).map((img) => img.imageId as string),
        ...(prefill?.run_id ? { run_id: prefill.run_id } : {}),
        ...(prefill?.session_id ? { session_id: prefill.session_id } : {}),
        source: prefill?.source ?? "manual",
        trigger_reasons: prefill?.trigger_reasons,
        ...pageContext(),
        website,
        ...(captcha ? { captcha } : {}),
      })
      showToast(`已提交（FB-${String(item.batch_seq).padStart(4, "0")}）`)
      for (const img of images) URL.revokeObjectURL(img.previewUrl)
      setImages([])
      setTitle("")
      setBody("")
      setCaptcha("")
      setCaptchaNeeded(false)
      onSubmitted?.(item)
      onClose?.()
    } catch (err) {
      if (err instanceof ApiError && err.code === "CAPTCHA_REQUIRED") {
        setCaptchaNeeded(true)
        setError("")
      } else {
        setError(errorWithCode(err))
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div data-testid="feedback-form" onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
      <div className="feedback-field">
        <span className="feedback-label">类型</span>
        <div className="rxy-input-shell" data-testid="feedback-kind" role="group">
          {KINDS.map((option) => (
            <button
              key={option.id}
              type="button"
              className={`rxy-seg-option${kind === option.id ? " active" : ""}`}
              aria-pressed={kind === option.id}
              onClick={() => setKind(option.id)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="feedback-field">
        <label className="feedback-label" htmlFor="feedback-module">涉及模块</label>
        <div className="rxy-input-shell">
          <select
            id="feedback-module"
            className="rxy-input"
            value={module}
            onChange={(event) => setModule(event.target.value)}
          >
            {MODULES.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {kind === "bug" ? (
        <div className="feedback-field">
          <span className="feedback-label">严重程度</span>
          <div className="rxy-input-shell" role="group">
            {SEVERITIES.map((option) => (
              <button
                key={option.id}
                type="button"
                className={`rxy-seg-option${severity === option.id ? " active" : ""}`}
                aria-pressed={severity === option.id}
                onClick={() => setSeverity(option.id)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="feedback-field">
        <label className="feedback-label" htmlFor="feedback-title">标题</label>
        <div className="rxy-input-shell">
          <input
            id="feedback-title"
            className="rxy-input"
            value={title}
            maxLength={120}
            placeholder="一句话描述问题或建议"
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>
      </div>

      <div className="feedback-field">
        <label className="feedback-label" htmlFor="feedback-body">
          描述
          <span className="rxy-tabular-nums" style={{ float: "right", opacity: 0.6 }}>
            {body.length}/{BODY_MAX}
          </span>
        </label>
        <div className="rxy-input-shell">
          <textarea
            id="feedback-body"
            className="rxy-input"
            value={body}
            rows={5}
            maxLength={BODY_MAX}
            placeholder="发生了什么？期望是什么？（Enter 换行，不会提交）"
            onChange={(event) => setBody(event.target.value)}
            onPaste={onPaste}
          />
        </div>
      </div>

      <div className="feedback-field">
        <span className="feedback-label">
          截图（可选，最多 {IMAGE_MAX_COUNT} 张，≤5MB，PNG/JPEG/WebP）
        </span>
        <div className="feedback-images">
          {images.map((img) => (
            <div key={img.localId} className="feedback-image-card">
              <img src={img.previewUrl} alt="" className="feedback-thumb" />
              <div className="feedback-image-meta">
                {img.error ? (
                  <>
                    <span className="feedback-image-error">{img.error}</span>
                    <button type="button" className="rxy-ghost-control" onClick={() => retryImage(img.localId)}>
                      重试
                    </button>
                  </>
                ) : img.imageId ? (
                  <span className="rxy-tabular-nums">{img.progress}%</span>
                ) : (
                  <span className="rxy-tabular-nums">上传中 {img.progress}%</span>
                )}
                <button
                  type="button"
                  className="rxy-ghost-control"
                  title="移除图片"
                  aria-label="移除图片"
                  onClick={() => removeImage(img.localId)}
                >
                  ×
                </button>
              </div>
            </div>
          ))}
          {images.length < IMAGE_MAX_COUNT ? (
            <button
              type="button"
              className="feedback-add-image rxy-ghost-control"
              onClick={() => fileInputRef.current?.click()}
            >
              + 添加图片
            </button>
          ) : null}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            multiple
            hidden
            onChange={(event: ChangeEvent<HTMLInputElement>) => {
              if (event.target.files?.length) addImages(event.target.files)
              event.target.value = ""
            }}
          />
        </div>
      </div>

      <p className="feedback-context-note">
        将随反馈附带：页面路径、服务端版本、浏览器与视口信息（不含对话内容）。
      </p>

      {/* honeypot：真人永远看不到/填不到这个字段；机器人填了则服务端假成功。 */}
      <input
        type="text"
        name="website"
        value={website}
        onChange={(event) => setWebsite(event.target.value)}
        tabIndex={-1}
        aria-hidden="true"
        autoComplete="off"
        className="rxy-honeypot"
      />

      {captchaNeeded ? (
        <div className="feedback-field" data-testid="feedback-captcha">
          <AltchaWidget onVerify={setCaptcha} />
        </div>
      ) : null}

      {error ? (
        <p className="feedback-error" role="alert">
          {error}
        </p>
      ) : null}

      <div className="feedback-actions">
        {onClose ? (
          <button type="button" className="rxy-ghost-control" onClick={onClose}>
            取消
          </button>
        ) : null}
        <button
          type="button"
          className="rxy-primary-btn"
          disabled={submitting || uploading}
          onClick={() => void submit()}
          data-testid="feedback-submit"
        >
          {submitting ? "提交中…" : uploading ? "图片上传中…" : "提交反馈"}
        </button>
      </div>
    </div>
  )
}
