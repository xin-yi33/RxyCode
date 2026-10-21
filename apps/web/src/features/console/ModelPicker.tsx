// CMP-07 模型选择按钮（PRD §6.1）：Composer 右下角、发送键左侧。
// 目录来自 GET /models（仅登录态加载），按 provider_name 分组；
// 选中值存进 ComposerDraft.modelRef（幂等范围含模型 → 改选即重置 requestId）。
import {
  useEffect,
  useMemo,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
} from "react"
import { Link } from "react-router"
import type { UseQueryResult } from "@tanstack/react-query"

import { IconCheck, IconChevronDown, IconSpinner } from "../../components/icons"
import { cn } from "../../lib/cn"
import { usePopover } from "../../lib/usePopover"
import type { ModelItem, ModelsCatalog } from "../../sdk/client"
import { useUi } from "../../state/ui"
import type { AuthStatus } from "../auth/useAuth"

const STATUS_REASON: Record<string, string> = {
  revoked: "连接已变更",
  no_key: "未配置密钥",
}

export type ModelPickerProps = {
  draftKey: string
  catalog: UseQueryResult<ModelsCatalog>
  authStatus: AuthStatus
  // 提交中/运行中禁用（PRD：运行中不可更换模型）。
  disabled?: boolean
  disabledReason?: string
  // 访客点击 → 打开登录提示层（与发送同一条路径）。
  onGuest: () => void
  // 选择了与当前不同的模型 → Composer 显示一行“下次任务生效”提示。
  onSwitched?: (label: string) => void
  // 选择完成后焦点回到输入框。
  returnFocusRef?: RefObject<HTMLElement | null>
}

export function ModelPicker({
  draftKey,
  catalog,
  authStatus,
  disabled = false,
  disabledReason,
  onGuest,
  onSwitched,
  returnFocusRef,
}: ModelPickerProps) {
  const draft = useUi((state) => state.drafts[draftKey])
  const patchDraft = useUi((state) => state.patchDraft)
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState("")
  const [highlight, setHighlight] = useState(0)
  const wrapRef = usePopover<HTMLDivElement>(open, () => setOpen(false))
  const optionId = (ref: string) => `model-opt-${ref}`

  const models = catalog.data?.models ?? []
  const defaultRef = catalog.data?.default_model_ref ?? null
  // undefined = 跟随服务端默认；catalog 未加载时按 null 处理。
  const selectedRef = draft?.modelRef !== undefined ? draft.modelRef : defaultRef
  const selectedModel = models.find((m) => m.model_ref === selectedRef) ?? null
  const selectedBroken =
    selectedRef != null && (!selectedModel || selectedModel.status !== "available")

  const groups = useMemo(() => {
    const f = filter.trim().toLowerCase()
    const map = new Map<string, ModelItem[]>()
    for (const m of models) {
      if (
        f &&
        !`${m.display_name} ${m.model_id} ${m.provider_name}`
          .toLowerCase()
          .includes(f)
      ) {
        continue
      }
      const key = m.provider_name || m.connection_name || "其他"
      const list = map.get(key) ?? []
      list.push(m)
      map.set(key, list)
    }
    return [...map.entries()]
  }, [models, filter])

  const usable = useMemo(
    () =>
      groups
        .flatMap(([, items]) => items)
        .filter((m) => m.status === "available"),
    [groups],
  )

  useEffect(() => setHighlight(0), [filter, open])
  useEffect(() => {
    if (!open) return
    const target = usable[highlight]
    if (target) {
      document.getElementById(optionId(target.model_ref))?.scrollIntoView({ block: "nearest" })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlight, open])

  let label = "选择模型"
  let title = "选择模型"
  if (authStatus === "pending") {
    title = "正在确认登录状态…"
  } else if (authStatus === "authed") {
    if (catalog.isPending) {
      label = "加载模型…"
      title = "正在加载模型目录"
    } else if (catalog.isError) {
      label = "模型加载失败"
      title = "模型目录加载失败，点击可重试"
    } else if (selectedRef != null) {
      if (selectedBroken) {
        label = "模型不可用"
        title = "所选模型已失效，请重新选择"
      } else if (selectedModel) {
        const provider = selectedModel.provider_name
        label = `${provider ? `${provider} · ` : ""}${selectedModel.display_name || selectedModel.model_id}`
        title = label
      }
    }
  }
  if (disabled && disabledReason) title = disabledReason

  const choose = (item: ModelItem) => {
    if (item.status !== "available") return
    // 模型属于幂等范围 —— 换模型即换 request_id。
    const changed = item.model_ref !== selectedRef
    patchDraft(draftKey, { modelRef: item.model_ref, requestId: "" })
    setOpen(false)
    setFilter("")
    if (changed) onSwitched?.(item.display_name || item.model_id)
    const focusTarget = returnFocusRef?.current
    if (focusTarget) focusTarget.focus()
  }

  const onTriggerClick = () => {
    if (disabled) return
    if (authStatus === "guest") {
      onGuest()
      return
    }
    if (authStatus === "pending") return
    setOpen((value) => !value)
  }

  const onMenuKeyDown = (event: ReactKeyboardEvent) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault()
      if (usable.length === 0) return
      setHighlight(
        (h) => (h + (event.key === "ArrowDown" ? 1 : -1) + usable.length) % usable.length,
      )
      return
    }
    if (event.key === "Enter" && event.target instanceof HTMLInputElement) {
      // 搜索框里的 Enter = 选中当前高亮项；选项按钮自身 Enter 走 click。
      event.preventDefault()
      const item = usable[highlight]
      if (item) choose(item)
    }
  }

  return (
    <div className="relative" ref={wrapRef}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`选择模型：${label}`}
        title={title}
        disabled={disabled}
        onClick={onTriggerClick}
        className={
          "flex max-w-[11rem] items-center gap-1.5 rounded-full border " +
          "border-border bg-transparent px-3 py-1.5 text-xs text-muted-ink " +
          "outline-none hover:bg-sidebar disabled:opacity-60 sm:max-w-[15rem]"
        }
      >
        {authStatus === "authed" && catalog.isPending ? (
          <IconSpinner size={12} />
        ) : null}
        <span className="min-w-0 truncate">{label}</span>
        {authStatus === "authed" && selectedModel && !selectedBroken ? (
          <span className="shrink-0 rounded-full bg-border px-1.5 py-0.5 text-[10px] leading-none text-muted-ink">
            {selectedModel.source === "platform" ? "平台" : "个人"}
          </span>
        ) : null}
        <IconChevronDown size={12} className="shrink-0" />
      </button>
      {open ? (
        <div
          role="dialog"
          aria-label="选择模型"
          className={
            "absolute bottom-full right-0 z-40 mb-2 w-72 " +
            "max-w-[calc(100vw-1rem)] overflow-hidden rounded-xl border " +
            "border-border bg-card shadow-lg"
          }
          onKeyDown={onMenuKeyDown}
        >
          {catalog.isPending ? (
            <p className="p-3 text-xs text-muted">正在加载模型目录…</p>
          ) : catalog.isError ? (
            <div className="space-y-2 p-3">
              <p className="text-xs text-failure">模型目录加载失败</p>
              <div className="flex items-center gap-3 text-xs">
                <button
                  type="button"
                  className="underline"
                  onClick={() => void catalog.refetch()}
                >
                  重试
                </button>
                <Link
                  className="underline"
                  to="/app/settings?section=models"
                  onClick={() => setOpen(false)}
                >
                  模型设置
                </Link>
              </div>
            </div>
          ) : models.length === 0 ? (
            <div className="space-y-2 p-3">
              <p className="text-xs text-muted">尚未添加模型</p>
              <Link
                className="text-xs underline"
                to="/app/settings?section=models"
                onClick={() => setOpen(false)}
              >
                添加服务商 / API Key
              </Link>
            </div>
          ) : (
            <>
              {selectedBroken ? (
                <p className="border-b border-border px-3 py-2 text-xs text-failure">
                  当前所选模型不可用，请重新选择
                </p>
              ) : null}
              <div className="border-b border-border p-2">
                <input
                  autoFocus
                  value={filter}
                  onChange={(event) => setFilter(event.target.value)}
                  placeholder="搜索模型…"
                  aria-label="搜索模型"
                  className={
                    "w-full rounded-md border border-border bg-background " +
                    "px-2 py-1.5 text-xs outline-none focus:border-muted"
                  }
                />
              </div>
              <div
                role="listbox"
                aria-label="可用模型"
                aria-activedescendant={
                  usable[highlight] ? optionId(usable[highlight].model_ref) : undefined
                }
                className="max-h-64 overflow-y-auto py-1"
              >
                {groups.map(([group, items]) => (
                  <div key={group}>
                    <p className="px-3 pb-1 pt-2 text-[11px] font-medium text-muted">
                      {group}
                    </p>
                    {items.map((m) => {
                      const isUsable = m.status === "available"
                      const isSelected = m.model_ref === selectedRef
                      const isHighlighted =
                        usable[highlight]?.model_ref === m.model_ref
                      return (
                        <button
                          key={m.model_ref}
                          id={optionId(m.model_ref)}
                          type="button"
                          role="option"
                          aria-selected={isSelected}
                          disabled={!isUsable}
                          title={
                            isUsable
                              ? `${m.provider_name} · ${m.display_name || m.model_id}`
                              : (STATUS_REASON[m.status] ?? "当前不可用")
                          }
                          onClick={() => choose(m)}
                          className={cn(
                            "flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs",
                            isUsable
                              ? "hover:bg-sidebar"
                              : "cursor-not-allowed opacity-60",
                            isHighlighted && isUsable ? "bg-sidebar" : "",
                          )}
                        >
                          <span className="w-3.5 shrink-0 text-foreground">
                            {isSelected ? <IconCheck size={12} /> : null}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate">
                              {m.display_name || m.model_id}
                            </span>
                            <span className="block truncate font-mono text-[10px] text-muted">
                              {m.model_id}
                            </span>
                          </span>
                          {m.model_ref === defaultRef ? (
                            <span className="shrink-0 rounded-full bg-success/15 px-1.5 py-0.5 text-[10px] text-success-ink">
                              默认
                            </span>
                          ) : null}
                          {!isUsable ? (
                            <span className="shrink-0 rounded-full bg-border px-1.5 py-0.5 text-[10px] text-muted-ink">
                              {STATUS_REASON[m.status] ?? "不可用"}
                            </span>
                          ) : null}
                          {m.source === "platform" ? (
                            <span className="shrink-0 rounded-full bg-border px-1.5 py-0.5 text-[10px] text-muted-ink">
                              平台
                            </span>
                          ) : null}
                        </button>
                      )
                    })}
                  </div>
                ))}
                {groups.length === 0 ? (
                  <p className="px-3 py-3 text-xs text-muted">
                    没有匹配“{filter}”的模型
                  </p>
                ) : null}
              </div>
              <div className="border-t border-border p-2">
                <Link
                  to="/app/settings?section=models"
                  onClick={() => setOpen(false)}
                  className="block rounded-md px-2 py-1.5 text-xs text-muted-ink hover:bg-sidebar"
                >
                  管理模型…
                </Link>
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  )
}
