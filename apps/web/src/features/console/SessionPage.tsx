import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useParams } from "react-router"

import { IconArrowDown } from "../../components/icons"
import { Button } from "../../components/ui/button"
import { Modal } from "../../components/ui/dialog"
import {
  createClient,
  type ArtifactItem,
  type PreviewJob,
  type RunSummary,
} from "../../sdk/client"
import { isUnauthorized } from "../../sdk/errors"
import FeedbackForm, { type FeedbackPrefill } from "../feedback/FeedbackForm"
import { AutoPromptCard } from "../feedback/AutoPromptCard"
import { useAutoFeedbackPrompt } from "../feedback/useAutoFeedbackPrompt"
import { useUi } from "../../state/ui"
import { PreviewDrawer } from "../preview/PreviewDrawer"
import { SplitWorkspace } from "../preview/SplitWorkspace"
import { ArtifactRows } from "../runs/ArtifactRows"
import { RunTimeline } from "../runs/RunTimeline"
import { isActiveRunStatus, isTerminalRunStatus } from "../runs/status"
import type { RunTerminalSignal } from "../feedback/autoPrompt"
import {
  useChatScrollController,
  type ScrollAnchor,
} from "../timeline/useChatScrollController"
import { Composer } from "./Composer"
import { SessionFiles } from "./SessionFiles"

const api = createClient()

// 历史分页按会话隔离：切到另一个会话时旧分页结果既不显示也不参与游标，
// 避免旧会话的晚到数据混进新会话。
type OlderPage = {
  sessionId: string
  runs: RunSummary[]
  cursor: string | null
}

function RunCard({
  run,
  onPreview,
  onTerminal,
  onFeedback,
}: {
  run: RunSummary
  onPreview: (artifact: ArtifactItem) => void
  onTerminal: (signal: RunTerminalSignal) => void
  onFeedback: () => void
}) {
  // W9-F4: 用户消息气泡、状态行、工具/审批/问题/Final 全部由 RunTimeline
  // 渲染 —— 这里不再画重复的状态行。模型行回显提交时的解析快照
  // （FR-17）；历史 run 没有记录就如实标注，不用当前选择补写过去。
  const model = run.model
  return (
    <article className="space-y-3">
      <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <span>
          模型：
          {model ? (model.display_name || model.model_id) : "未记录（历史任务）"}
        </span>
        {model?.provider_name ? <span>· {model.provider_name}</span> : null}
        {model ? (
          <span className="rounded-full bg-border px-1.5 py-0.5 text-muted-ink">
            {model.credential_source === "platform" ? "平台" : "个人"}
          </span>
        ) : null}
        {isTerminalRunStatus(run.status) ? (
          <button
            type="button"
            className="rxy-ghost-control rounded px-1 text-muted-ink"
            title="反馈此回答"
            aria-label="反馈此回答"
            data-testid="run-feedback-btn"
            onClick={onFeedback}
          >
            ⚑
          </button>
        ) : null}
      </p>
      <RunTimeline run={run} onTerminal={onTerminal} />
      <ArtifactRows runId={run.run_id} status={run.status} onPreview={onPreview} />
    </article>
  )
}

export function SessionPage() {
  const { sessionId = "" } = useParams()
  const [olderPage, setOlderPage] = useState<OlderPage | null>(null)
  const [preview, setPreview] = useState<{ title: string; job: PreviewJob | null } | null>(null)
  // Preview data alone must not reopen a user-collapsed pane, but clicking an
  // artifact again must — this nonce is that explicit open signal.
  const [previewNonce, setPreviewNonce] = useState(0)
  const [feedbackTarget, setFeedbackTarget] = useState<FeedbackPrefill | null>(null)
  const pendingAnchorRef = useRef<ScrollAnchor | null>(null)
  const seenRunsRef = useRef<Set<string>>(new Set())

  // v1.4.6 自动反馈询问：RunTimeline 上报实时终态信号；本层观察新 run
  // 的用户消息补充后续信号（repeated_prompt / negative_followup）。
  const autoPrompt = useAutoFeedbackPrompt(sessionId)
  const draftText = useUi((s) => s.drafts[sessionId]?.text ?? "")
  const prevDraftRef = useRef(draftText)
  useEffect(() => {
    const prev = prevDraftRef.current
    prevDraftRef.current = draftText
    if (prev.trim() === "" && draftText.trim() !== "") {
      autoPrompt.observeComposerActivity()
    }
  }, [draftText, autoPrompt])

  // 整个会话页只有这一个滚动容器（chat-scroll）：跟随底部、用户上滚暂停、
  // jump-to-latest、会话切换重置都由控制器统一负责。
  const scroll = useChatScrollController(sessionId)
  const { restoreAnchor } = scroll

  const previewPoll = useQuery({
    queryKey: ["preview-job", preview?.job?.preview_id],
    enabled: Boolean(
      preview?.job &&
        (preview.job.status === "queued" || preview.job.status === "running"),
    ),
    queryFn: ({ signal }) => api.getPreview(preview!.job!.preview_id, signal),
    refetchInterval: 1_000,
  })
  const liveJob = (previewPoll.data as PreviewJob | undefined) ?? preview?.job ?? null
  const openPreview = (artifact: ArtifactItem) => {
    const title = artifact.filename || artifact.relative_path
    setPreviewNonce((n) => n + 1)
    setPreview({ title, job: null })
    void api
      .createPreview(artifact.artifact_id)
      .then((job) => setPreview({ title, job }))
      .catch(() => setPreview(null))
  }
  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: ({ signal }) => api.getSession(sessionId, signal),
  })
  const runs = useQuery({
    queryKey: ["sessionRuns", sessionId],
    queryFn: ({ signal }) => api.listSessionRuns(sessionId, { limit: 20 }, signal),
    refetchInterval: (query) => {
      const items = query.state.data?.runs ?? []
      return items.some((run) => isActiveRunStatus(run.status)) ? 5_000 : false
    },
  })

  const older = olderPage && olderPage.sessionId === sessionId ? olderPage : null
  const nextCursor = older ? older.cursor : (runs.data?.next_cursor ?? null)

  const loadEarlier = () => {
    if (!nextCursor) return
    // 上方插入历史前先记录视觉锚点：用户上滚阅读时加载更早，滚动位置不能跳。
    pendingAnchorRef.current = scroll.isFollowing() ? null : scroll.captureAnchor()
    const requestedFor = sessionId
    void api
      .listSessionRuns(requestedFor, { limit: 20, before: nextCursor })
      .then((page) => {
        setOlderPage((current) => ({
          sessionId: requestedFor,
          runs: [...(current?.sessionId === requestedFor ? current.runs : []), ...page.runs],
          cursor: page.next_cursor,
        }))
      })
  }

  // 历史插入后恢复锚点（浏览器 scroll anchoring 已处理时保持在 2px 内不再写）。
  useLayoutEffect(() => {
    const anchor = pendingAnchorRef.current
    pendingAnchorRef.current = null
    if (!anchor) return
    restoreAnchor(anchor)
  }, [olderPage, restoreAnchor])

  if (session.isError && !isUnauthorized(session.error)) {
    return (
      <div role="alert" className="p-6 text-sm text-muted">
        无法连接服务器{" "}
        <button type="button" className="underline" onClick={() => void session.refetch()}>
          重试
        </button>
      </div>
    )
  }

  // Backend returns newest-first; render oldest-first like a chat log.
  const ordered = [...(older?.runs ?? []), ...(runs.data?.runs ?? [])].reverse()
  const active = ordered.find((run) => isActiveRunStatus(run.status)) ?? null

  // 新出现的 run = 用户发出的下一条消息 —— 自动询问的“后续消息信号”。
  // 只看首次进入列表的 run_id，且分页加载进来的历史 run 不算后续
  // （候选窗内点「加载更早」不能把旧 run 的抱怨记成 negative_followup）。
  useEffect(() => {
    const seen = seenRunsRef.current
    const pagedIds = new Set((older?.runs ?? []).map((r) => r.run_id))
    for (const run of ordered) {
      if (seen.has(run.run_id)) continue
      seen.add(run.run_id)
      if (pagedIds.has(run.run_id)) continue
      const at = run.created_at ? Date.parse(run.created_at) : Date.now()
      autoPrompt.observeFollowup(run.message, at)
    }
  }, [ordered, older?.runs, autoPrompt])

  const archived = session.data?.archived === true || Boolean(session.data?.archived_at)

  return (
    <SplitWorkspace
      preview={
        preview ? (
          <PreviewDrawer
            job={liveJob}
            title={preview.title}
            open={preview !== null}
            onClose={() => setPreview(null)}
          />
        ) : null
      }
      onPreviewClose={() => setPreview(null)}
      openSignal={previewNonce}
    >
      <div className="rxy-session relative flex h-full min-h-0 w-full flex-col">
        <div className="relative min-h-0 flex-1">
          <div
            ref={scroll.scrollRef}
            data-testid="chat-scroll"
            role="log"
            aria-label="会话消息"
            tabIndex={0}
            className={
              "rxy-chat-scroll h-full min-h-0 overflow-y-auto overscroll-contain " +
              "px-4 pb-6 pt-4 outline-none focus-visible:ring-2 focus-visible:ring-running/50"
            }
          >
            <div ref={scroll.contentRef} className="mx-auto w-full max-w-3xl">
              {archived ? (
                <div
                  role="status"
                  className="mb-3 flex items-center justify-between gap-2 rounded-lg border border-waiting/40 bg-waiting/10 px-3 py-2 text-sm text-waiting-ink"
                >
                  <span>此会话已归档，内容只读。取消归档后可继续对话。</span>
                  <button
                    type="button"
                    className="shrink-0 underline"
                    onClick={() => {
                      void api
                        .unarchiveSession(sessionId, {
                          expected_revision: session.data?.revision,
                        })
                        .then(() => void session.refetch())
                    }}
                  >
                    取消归档
                  </button>
                </div>
              ) : null}
              {runs.isPending ? (
                <p className="py-8 text-center text-sm text-muted">正在加载任务…</p>
              ) : null}
              {ordered.length === 0 && runs.isSuccess ? (
                <p className="py-8 text-center text-sm text-muted">
                  这个会话还没有任务，从下方输入框开始。
                </p>
              ) : null}
              {nextCursor ? (
                <div className="pb-2 text-center">
                  <Button variant="outline" size="sm" onClick={loadEarlier}>
                    加载更早的任务
                  </Button>
                </div>
              ) : null}
              <ol className="flex-1 space-y-8 pb-6">
                {ordered.map((run) => (
                  <li key={run.run_id} id={`run-${run.run_id}`}>
                    <RunCard
                      run={run}
                      onPreview={openPreview}
                      onTerminal={autoPrompt.observeTerminal}
                      onFeedback={() =>
                        setFeedbackTarget({
                          run_id: run.run_id,
                          session_id: sessionId,
                          module: "run_output",
                          kind: "content_quality",
                          source: "manual",
                        })
                      }
                    />
                  </li>
                ))}
              </ol>
            </div>
          </div>
          <button
            type="button"
            data-testid="chat-jump-to-latest"
            onClick={scroll.scrollToLatest}
            aria-label="回到最新消息"
            className={
              (scroll.showJumpToLatest ? "flex" : "hidden") +
              " absolute bottom-4 left-1/2 z-10 -translate-x-1/2 items-center gap-1 " +
              "rounded-full border border-border bg-card px-3 py-1.5 text-xs " +
              "text-foreground shadow-sm"
            }
          >
            <IconArrowDown size={13} />
            回到最新
          </button>
        </div>
        {archived ? null : (
          <div className="shrink-0 space-y-2 bg-background">
            <div className="mx-auto w-full max-w-3xl px-4">
              <SessionFiles sessionId={sessionId} hasActive={active !== null} />
            </div>
            <Composer sessionId={sessionId} activeRun={active} />
          </div>
        )}
        {autoPrompt.card ? (
          <AutoPromptCard
            card={autoPrompt.card}
            onRespond={() => {
              const card = autoPrompt.respond()
              if (card) {
                setFeedbackTarget({
                  run_id: card.runId,
                  session_id: card.sessionId,
                  module: "run_output",
                  kind: "content_quality",
                  source: "auto_prompt",
                  trigger_reasons: card.reasons,
                })
              }
            }}
            onDismiss={autoPrompt.dismiss}
            onNever={autoPrompt.disableAutoPrompt}
          />
        ) : null}
        {feedbackTarget ? (
          <Modal onClose={() => setFeedbackTarget(null)} label="反馈此回答" className="max-w-lg">
            <h3 className="mb-3 text-base font-semibold">反馈此回答</h3>
            <FeedbackForm
              prefill={feedbackTarget}
              onClose={() => setFeedbackTarget(null)}
            />
          </Modal>
        ) : null}
      </div>
    </SplitWorkspace>
  )
}
