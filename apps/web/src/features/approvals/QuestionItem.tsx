import { useEffect, useState, type FormEvent } from "react"
import { useQuery } from "@tanstack/react-query"

import { Button } from "../../components/ui/button"
import { ApiError, createClient } from "../../sdk/client"
import type { TimelineItem } from "../runs/eventReducer"

const api = createClient()

type QuestionItemData = Extract<TimelineItem, { kind: "question" }>

// F5 问题卡：header 粗体标题 + prompt 正文 + 选项按钮组（点击直接提交 value）
// + 自由输入框。提交状态处理与审批卡一致；question.resolved 折叠为一行。
export function QuestionItem({
  runId,
  item,
}: {
  runId: string
  item: QuestionItemData
}) {
  const [draft, setDraft] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")
  // 本地乐观态：POST 成功后立即折叠为“你的回答：…”。
  const [localAnswer, setLocalAnswer] = useState<string | null>(null)
  const [stale, setStale] = useState(false)

  const answer = localAnswer ?? item.answer
  // question.requested 事件驱动：挂载时只拉一次 pending 列表确认仍在等
  // 回答（事件本体已带 header/options，无需轮询）。不在 pending 里 →
  // 已被别处处理 → 折叠。网络错误不算已处理。
  const pending = useQuery({
    queryKey: ["questions", runId, item.questionId],
    queryFn: ({ signal }) => api.listQuestions(runId, signal),
    enabled: !answer && !stale,
    staleTime: 0,
    refetchInterval: false,
    refetchOnWindowFocus: false,
    retry: 0,
  })
  useEffect(() => {
    if (answer || stale || !pending.isSuccess) return
    const found = pending.data.questions.some(
      (row) => row.question_id === item.questionId,
    )
    if (!found) setStale(true)
  }, [answer, stale, pending.isSuccess, pending.data, item.questionId])
  if (stale) {
    return (
      <p data-question-id={item.questionId} className="text-xs text-muted">
        {item.header || item.prompt} · 已被处理
      </p>
    )
  }
  if (answer) {
    return (
      <p data-question-id={item.questionId} className="text-xs text-muted">
        {item.header || item.prompt} · 你的回答：{answer}
      </p>
    )
  }

  const submit = async (value: string) => {
    const text = value.trim()
    if (submitting || !text) return
    setSubmitting(true)
    setError("")
    try {
      await api.answerQuestion(runId, { question_id: item.questionId, answer: text })
      setLocalAnswer(text)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // QUESTION_STALE —— 重新拉一次确认是否已经被处理。
        try {
          const again = await api.listQuestions(runId)
          const still = again.questions.some(
            (row) => row.question_id === item.questionId,
          )
          if (still) {
            setError("问题状态已变化，请重试")
          } else {
            setStale(true)
          }
        } catch {
          setError("提交失败，可重试")
        }
      } else {
        setError("提交失败，可重试")
      }
    } finally {
      setSubmitting(false)
    }
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    void submit(draft)
  }

  return (
    <article
      data-question-id={item.questionId}
      className="rounded-lg border border-border bg-card p-3"
    >
      {item.header ? (
        <p className="text-sm font-semibold">{item.header}</p>
      ) : null}
      {item.prompt ? (
        <p className="mt-1 whitespace-pre-wrap text-sm">{item.prompt}</p>
      ) : null}
      {item.options.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {item.options.map((option) => (
            <Button
              key={option.value || option.label}
              size="sm"
              variant="outline"
              disabled={submitting}
              onClick={() => void submit(option.value)}
            >
              {submitting ? "提交中…" : option.label || option.value}
            </Button>
          ))}
        </div>
      ) : null}
      {item.inputType === "text" ? (
        // 服务端对带选项的问题只接受选项值 —— choice 不渲染自由输入。
        <form onSubmit={onSubmit} className="mt-2 flex items-center gap-2">
          <input
            type="text"
            aria-label="回答"
            placeholder="输入你的回答…"
            className={
              "min-w-0 flex-1 rounded-md border border-border bg-background " +
              "px-2.5 py-1.5 text-sm outline-none focus:border-muted"
            }
            value={draft}
            disabled={submitting}
            onChange={(event) => setDraft(event.target.value)}
          />
          <Button type="submit" size="sm" disabled={submitting || !draft.trim()}>
            {submitting ? "提交中…" : "发送"}
          </Button>
        </form>
      ) : null}
      {error ? (
        <p role="alert" className="mt-2 text-xs text-failure">
          {error}
        </p>
      ) : null}
    </article>
  )
}
