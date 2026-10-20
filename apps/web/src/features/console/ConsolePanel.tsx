import { useEffect, useMemo, useState, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { useParams } from "react-router"

import { IconCheck, IconClose, IconCopy } from "../../components/icons"
import { createClient, type RunSummary } from "../../sdk/client"
import { useUi } from "../../state/ui"
import type { RunView } from "../runs/eventReducer"
import { isActiveRunStatus } from "../runs/status"
import { fetchRunView } from "../runs/useRunEvents"
import { StatusChip } from "../timeline/Timeline"
import { ToolRow } from "../timeline/ToolRow"

const api = createClient()

type Tab = "activity" | "run" | "usage"
type ToolItem = Extract<RunView["timeline"][number], { kind: "tool" }>

const TABS: { value: Tab; label: string }[] = [
  { value: "activity", label: "活动" },
  { value: "run", label: "运行" },
  { value: "usage", label: "用量" },
]

const PROFILE_TEXT: Record<string, string> = {
  confirm: "需要确认",
  full: "完全自动",
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    const done = () => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    }
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => undefined)
    } else {
      const area = document.createElement("textarea")
      area.value = text
      document.body.appendChild(area)
      area.select()
      try {
        document.execCommand("copy")
        done()
      } catch {
        // 剪贴板不可用 —— 静默失败
      }
      document.body.removeChild(area)
    }
  }
  return (
    <button
      type="button"
      aria-label={copied ? "已复制" : "复制"}
      title={copied ? "已复制" : "复制"}
      className="rounded p-1 text-muted hover:bg-sidebar"
      onClick={copy}
    >
      {copied ? <IconCheck size={13} /> : <IconCopy size={13} />}
    </button>
  )
}

function Field({ label, children }: { label: string; children?: ReactNode }) {
  return (
    <div className="flex items-start gap-2 text-xs">
      <dt className="w-20 shrink-0 pt-0.5 text-muted">{label}</dt>
      <dd className="min-w-0 flex-1 break-all">{children}</dd>
    </div>
  )
}

function ActivityTab({ views }: { views: RunView[] }) {
  const [failedOnly, setFailedOnly] = useState(false)
  const rows = views.flatMap((view) =>
    view.timeline
      .filter((item): item is ToolItem => item.kind === "tool")
      .filter((item) => !failedOnly || item.status === "failed")
      .map((item) => ({ view, item })),
  )
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex gap-1 px-3 pt-2" role="group" aria-label="活动过滤">
        <button
          type="button"
          aria-pressed={!failedOnly}
          className={
            "rounded-full px-2.5 py-1 text-xs " +
            (!failedOnly ? "bg-foreground text-background" : "text-muted hover:bg-sidebar")
          }
          onClick={() => setFailedOnly(false)}
        >
          全部
        </button>
        <button
          type="button"
          aria-pressed={failedOnly}
          className={
            "rounded-full px-2.5 py-1 text-xs " +
            (failedOnly ? "bg-foreground text-background" : "text-muted hover:bg-sidebar")
          }
          onClick={() => setFailedOnly(true)}
        >
          仅失败
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {rows.length === 0 ? (
          <p className="px-1 py-4 text-center text-xs text-muted">
            {failedOnly ? "没有失败的工具调用" : "还没有工具活动"}
          </p>
        ) : null}
        {rows.map(({ view, item }) => (
          <div key={`${view.runId}-${item.seq}-${item.callId}`}>
            <p className="px-1 pb-0.5 font-mono text-[11px] text-muted">
              {view.runId.slice(0, 8)} · seq {item.seq}
            </p>
            <ToolRow item={item} />
          </div>
        ))}
      </div>
    </div>
  )
}

function RunTab({ runs, views }: { runs: RunSummary[]; views: RunView[] }) {
  const byId = useMemo(() => new Map(views.map((view) => [view.runId, view])), [views])
  if (runs.length === 0) {
    return <p className="p-3 text-xs text-muted">这个会话还没有任务。</p>
  }
  return (
    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
      {runs.map((run) => {
        const view = byId.get(run.run_id)
        const resumes = Math.max(0, (view?.leaseEpochs.length ?? 0) - 1)
        return (
          <dl
            key={run.run_id}
            data-run-meta={run.run_id}
            className="space-y-1.5 rounded-lg border border-border bg-card p-3"
          >
            <Field label="Run ID">
              <span className="flex items-center gap-1 font-mono">
                <span className="min-w-0 truncate">{run.run_id}</span>
                <CopyButton text={run.run_id} />
              </span>
            </Field>
            <Field label="状态">
              <StatusChip status={view?.status || run.status} />
            </Field>
            <Field label="创建时间">
              {run.created_at ? new Date(run.created_at).toLocaleString() : "—"}
            </Field>
            <Field label="续接次数">{resumes}</Field>
            <Field label="最新 seq">{view?.lastSeq ?? "—"}</Field>
            <Field label="权限模式">
              {PROFILE_TEXT[run.permission_profile] ?? run.permission_profile ?? "—"}
            </Field>
          </dl>
        )
      })}
    </div>
  )
}

function UsageTab({ runs, views }: { runs: RunSummary[]; views: RunView[] }) {
  const byId = useMemo(() => new Map(views.map((view) => [view.runId, view])), [views])
  let totalTokens = 0
  let totalAmount = 0
  let anyTokens = false
  let anyAmount = false
  let currency = ""
  for (const view of views) {
    if (view.usage.tokens !== undefined) {
      anyTokens = true
      totalTokens += view.usage.tokens
    }
    if (view.usage.amount !== undefined) {
      const parsed = Number(view.usage.amount)
      if (Number.isFinite(parsed)) {
        anyAmount = true
        totalAmount += parsed
        if (view.usage.currency) currency = view.usage.currency
      }
    }
  }
  return (
    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
      {runs.length === 0 ? (
        <p className="text-xs text-muted">这个会话还没有任务。</p>
      ) : null}
      {runs.map((run) => {
        const usage = byId.get(run.run_id)?.usage
        return (
          <dl
            key={run.run_id}
            className="space-y-1.5 rounded-lg border border-border bg-card p-3"
          >
            <Field label="Run ID">
              <span className="font-mono">{run.run_id.slice(0, 8)}…</span>
            </Field>
            <Field label="模型">{usage?.modelId || "未上报"}</Field>
            <Field label="Tokens">
              {usage?.tokens !== undefined ? usage.tokens.toLocaleString() : "未上报"}
            </Field>
            <Field label="金额">
              {usage?.amount !== undefined
                ? `${usage.amount}${usage.currency ? ` ${usage.currency}` : ""}`
                : "未上报"}
            </Field>
          </dl>
        )
      })}
      {runs.length > 0 ? (
        <dl className="space-y-1.5 rounded-lg border border-border bg-sidebar p-3">
          <p className="pb-0.5 text-xs font-medium text-muted">会话合计</p>
          <Field label="Tokens">
            {anyTokens ? totalTokens.toLocaleString() : "未上报"}
          </Field>
          <Field label="金额">
            {anyAmount
              ? `${Number(totalAmount.toFixed(6))}${currency ? ` ${currency}` : ""}`
              : "未上报"}
          </Field>
        </dl>
      ) : null}
    </div>
  )
}

// W9-F5 控制台：活动 / 运行 / 用量 三页签。≥1280px 时是 400px 右侧面板，
// 以下为全屏覆盖层；Esc 或关闭按钮退出。旧的底部 steering 输入已由
// Composer 的停止键与这三页签取代。
export function ConsolePanel() {
  const params = useParams()
  const sessionId = params.sessionId ?? ""
  const setConsoleOpen = useUi((state) => state.setConsoleOpen)
  const [tab, setTab] = useState<Tab>("activity")

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConsoleOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [setConsoleOpen])

  const runs = useQuery({
    queryKey: ["sessionRuns", sessionId],
    queryFn: ({ signal }) => api.listSessionRuns(sessionId, { limit: 50 }, signal),
    enabled: sessionId.length > 0,
    refetchInterval: (query) =>
      (query.state.data?.runs ?? []).some((run) => isActiveRunStatus(run.status))
        ? 10_000
        : false,
  })
  const runList = useMemo(() => runs.data?.runs ?? [], [runs.data])
  const runIds = useMemo(() => runList.map((run) => run.run_id).join(","), [runList])

  // 每个 run 的 RunView（GET run + follow=0 全量回放）——活动/运行/用量共用。
  const views = useQuery({
    queryKey: ["runViews", sessionId, runIds],
    queryFn: ({ signal }) =>
      Promise.all(runIds.split(",").filter(Boolean).map((id) => fetchRunView(id, signal))),
    enabled: runIds.length > 0,
    refetchInterval: (query) =>
      (query.state.data ?? []).some((view) => isActiveRunStatus(view.status))
        ? 10_000
        : false,
  })
  const viewList = useMemo(() => views.data ?? [], [views.data])

  return (
    <aside
      aria-label="控制台"
      className={
        "fixed inset-0 z-50 flex flex-col bg-background " +
        "xl:static xl:z-auto xl:w-[400px] xl:shrink-0 xl:border-l xl:border-border"
      }
    >
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
        <h2 className="text-sm font-medium">控制台</h2>
        <nav className="ml-2 flex gap-1" aria-label="控制台页签">
          {TABS.map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={tab === item.value}
              className={
                "rounded-full px-3 py-1 text-xs " +
                (tab === item.value
                  ? "bg-foreground text-background"
                  : "text-muted hover:bg-sidebar")
              }
              onClick={() => setTab(item.value)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <button
          type="button"
          aria-label="关闭控制台"
          title="关闭控制台（Esc）"
          className="ml-auto rounded-md p-1.5 text-muted hover:bg-sidebar"
          onClick={() => setConsoleOpen(false)}
        >
          <IconClose size={16} />
        </button>
      </div>
      {!sessionId ? (
        <p className="p-4 text-xs text-muted">打开一个会话后这里会显示它的运行信息。</p>
      ) : runs.isPending ? (
        <p className="p-4 text-xs text-muted">正在加载…</p>
      ) : runs.isError ? (
        <p role="alert" className="p-4 text-xs text-muted">
          无法加载会话任务{" "}
          <button type="button" className="underline" onClick={() => void runs.refetch()}>
            重试
          </button>
        </p>
      ) : tab === "activity" ? (
        <ActivityTab views={viewList} />
      ) : tab === "run" ? (
        <RunTab runs={runList} views={viewList} />
      ) : (
        <UsageTab runs={runList} views={viewList} />
      )}
    </aside>
  )
}
