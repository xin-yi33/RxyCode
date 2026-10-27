// 设置 → 反馈：提交表单 + 我的反馈 + 自动询问开关 + 管理面板。
import { useEffect, useRef, useState } from "react"
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createClient,
  type FeedbackBatchSummary,
  type FeedbackItem,
} from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { useAuth } from "../auth/useAuth"
import FeedbackForm from "./FeedbackForm"
import { safeStorage, STORAGE_KEY as AUTO_PROMPT_KEY } from "./autoPrompt"
import "./feedback.css"

const api = createClient()

const STATE_TEXT: Record<string, string> = {
  new: "已收到",
  triaged: "已分类",
  in_progress: "处理中",
  resolved: "已解决",
  wontfix: "暂不处理",
  spam: "垃圾",
}

const KIND_TEXT: Record<string, string> = {
  bug: "Bug",
  suggestion: "优化建议",
  content_quality: "内容质量",
}

const MODULE_TEXT: Record<string, string> = {
  chat: "聊天",
  run_output: "回答内容",
  tools: "工具",
  files_preview: "文件预览",
  settings: "设置",
  auth: "登录",
  models_byok: "模型",
  mobile: "移动端",
  performance: "性能",
  other: "其他",
}

export const ITEM_STATES = ["new", "triaged", "in_progress", "resolved", "wontfix", "spam"] as const

export function batchLabel(seq: number): string {
  return `FB-${String(seq).padStart(4, "0")}`
}

function MyFeedbackList({ refreshKey }: { refreshKey: number }) {
  const query = useInfiniteQuery({
    queryKey: ["feedbackMine", refreshKey],
    queryFn: ({ pageParam, signal }) =>
      api.listMyFeedback({ cursor: pageParam || undefined, signal }),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 10_000,
  })
  const items = query.data?.pages.flatMap((page) => page.items) ?? []
  return (
    <section className="feedback-mine" data-testid="feedback-mine">
      <h3>我的反馈</h3>
      {query.isError ? <p className="feedback-error">{apiErrorText(query.error)}</p> : null}
      {!query.isLoading && items.length === 0 ? <p className="feedback-muted">还没有提交过反馈。</p> : null}
      {items.map((item) => (
        <article key={item.id} className="feedback-mine-item">
          <header>
            <strong>{item.title}</strong>
            <span className={`rxy-chip feedback-state-${item.state}`}>
              {STATE_TEXT[item.state] ?? item.state}
            </span>
          </header>
          <p className="feedback-muted">
            {batchLabel(item.batch_seq)} · {KIND_TEXT[item.kind] ?? item.kind} ·{" "}
            {MODULE_TEXT[item.module] ?? item.module}
            {item.created_at ? ` · ${new Date(item.created_at).toLocaleString()}` : ""}
          </p>
          {item.images.length > 0 ? (
            <div className="feedback-mine-thumbs">
              {item.images.map((img) => (
                <img
                  key={img.id}
                  src={`/api/v1/feedback/images/${img.id}`}
                  width={48}
                  height={48}
                  alt=""
                  loading="lazy"
                />
              ))}
            </div>
          ) : null}
        </article>
      ))}
      {query.hasNextPage ? (
        <button
          type="button"
          className="rxy-ghost-control"
          data-testid="feedback-mine-more"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage ? "加载中…" : "加载更多"}
        </button>
      ) : null}
    </section>
  )
}

function AdminPanel() {
  const queryClient = useQueryClient()
  const [openSeq, setOpenSeq] = useState<number | null>(null)
  const batches = useQuery({
    queryKey: ["feedbackBatches"],
    queryFn: ({ signal }) => api.listFeedbackBatches(signal),
    staleTime: 15_000,
  })
  const detail = useQuery({
    queryKey: ["feedbackBatch", openSeq],
    enabled: openSeq !== null,
    queryFn: ({ signal }) => api.getFeedbackBatch(openSeq as number, signal),
    staleTime: 10_000,
  })
  const closeMutation = useMutation({
    mutationFn: (seq: number) => api.closeFeedbackBatch(seq),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["feedbackBatches"] })
      void queryClient.invalidateQueries({ queryKey: ["feedbackBatch"] })
    },
  })
  const stateMutation = useMutation({
    mutationFn: ({ id, state }: { id: string; state: string }) =>
      api.patchFeedbackItem(id, { state }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["feedbackBatch"] })
    },
  })

  const list = batches.data?.batches ?? []
  return (
    <section className="feedback-admin" data-testid="feedback-admin">
      <h3>反馈管理</h3>
      {list.map((batch: FeedbackBatchSummary) => (
        <article key={batch.seq} className="feedback-batch">
          <header>
            <button
              type="button"
              className="rxy-ghost-control"
              onClick={() => setOpenSeq(openSeq === batch.seq ? null : batch.seq)}
              aria-expanded={openSeq === batch.seq}
            >
              {batch.label}
            </button>
            <span className="rxy-chip">{batch.status === "open" ? "收集中" : "已关闭"}</span>
            <span className="rxy-tabular-nums">
              {batch.item_count}/{batch.capacity}
            </span>
            <span className="feedback-muted rxy-tabular-nums">
              {(batch.build_commit || "").slice(0, 8)}
            </span>
            {batch.summary ? (
              <span className="rxy-chip">
                bug {batch.summary.by_kind?.bug ?? 0} · 建议{" "}
                {batch.summary.by_kind?.suggestion ?? 0}
              </span>
            ) : null}
            <a
              className="rxy-ghost-control"
              href={api.feedbackBatchExportUrl(batch.seq, "md")}
              download
            >
              导出 MD
            </a>
            <a
              className="rxy-ghost-control"
              href={api.feedbackBatchExportUrl(batch.seq, "json")}
              download
            >
              JSON
            </a>
            {batch.status === "open" ? (
              <button
                type="button"
                className="rxy-ghost-control"
                onClick={() => closeMutation.mutate(batch.seq)}
                disabled={closeMutation.isPending}
              >
                关闭批次
              </button>
            ) : null}
          </header>
          {openSeq === batch.seq && detail.data ? (
            <div className="feedback-batch-detail">
              {Object.entries(detail.data.groups).map(([module, items]) => (
                <div key={module}>
                  <h4>
                    {MODULE_TEXT[module] ?? module}（{items.length}）
                  </h4>
                  {(items as FeedbackItem[]).map((item) => (
                    <div key={item.id} className="feedback-admin-item">
                      <span className="feedback-muted">{item.title}</span>
                      <select
                        className="rxy-input"
                        value={item.state}
                        aria-label="反馈状态"
                        onChange={(event) =>
                          stateMutation.mutate({ id: item.id, state: event.target.value })
                        }
                      >
                        {ITEM_STATES.map((state) => (
                          <option key={state} value={state}>
                            {STATE_TEXT[state] ?? state}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          ) : null}
        </article>
      ))}
      {batches.data && list.length === 0 ? <p className="feedback-muted">暂无批次。</p> : null}
    </section>
  )
}

export default function FeedbackSection() {
  const { me } = useAuth()
  const [refreshKey, setRefreshKey] = useState(0)
  const [autoPrompt, setAutoPrompt] = useState(
    () => safeStorage().getItem(AUTO_PROMPT_KEY) !== "0",
  )
  const mounted = useRef(false)
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true
      return
    }
    safeStorage().setItem(AUTO_PROMPT_KEY, autoPrompt ? "1" : "0")
  }, [autoPrompt])

  return (
    <div className="settings-section" data-testid="settings-feedback">
      <h2>反馈</h2>
      <p className="feedback-muted">
        报告 bug 或提出改进建议。可附截图；我们会自动记录页面路径与版本信息。
      </p>
      <FeedbackForm onSubmitted={() => setRefreshKey((k) => k + 1)} />
      <label className="feedback-toggle">
        <input
          type="checkbox"
          checked={autoPrompt}
          onChange={(event) => setAutoPrompt(event.target.checked)}
          data-testid="feedback-autoprompt-toggle"
        />
        在回答异常时自动询问是否反馈
      </label>
      <MyFeedbackList refreshKey={refreshKey} />
      {me?.feedback_admin ? <AdminPanel /> : null}
    </div>
  )
}
