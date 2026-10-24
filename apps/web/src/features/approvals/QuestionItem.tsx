import { useEffect, useMemo, useRef, useState, type FormEvent } from "react"
import { useQuery } from "@tanstack/react-query"

import { Button } from "../../components/ui/button"
import { ApiError, createClient } from "../../sdk/client"
import {
  beginQuestionAnswer,
  finishQuestionAnswer,
  isQuestionAnswered,
} from "./questionAnswerGuard"
import { answerLabel, numberedQuestionOptions } from "./questionOptions"
import type { TimelineItem } from "../runs/eventReducer"

const api = createClient()

type QuestionItemData = Extract<TimelineItem, { kind: "question" }>

// F5 问题卡：header 粗体标题 + prompt 正文 + 垂直编号选项列表 + 自由输入框。
//
// 交互契约（云端问题卡事故回归）：
// - 选项严格按 payload 顺序渲染成垂直列表：1. 2. 3. …（编号只由顺序决定，
//   组件从不排序/重排；OL/LI 语义 + aria-label 供读屏使用）。
// - 点一个选项只提交这一个选项的 value —— 恰好一次 POST；同步 ref +
//   模块级 guard 挡住双击/重复挂载/重放造成的重复提交。
// - 提交中只把“被点中的那一项”标成 aria-busy + 提交中…，其余选项保留
//   各自 label（旧实现会把所有按钮文案一起换成“提交中…”，看起来像全部
//   选项都被提交了）。
// - 成功后折叠成一行“你的回答：<label>”（value → label 映射），409/stale
//   仍走重新确认分支。
export function QuestionItem({
  runId,
  item,
}: {
  runId: string
  item: QuestionItemData
}) {
  const options = useMemo(
    () => numberedQuestionOptions(item.options),
    [item.options],
  )
  const [draft, setDraft] = useState("")
  const [submitting, setSubmitting] = useState(false)
  // 只标记被点中的选项；其余选项的 label 保持可见。
  const [pendingValue, setPendingValue] = useState<string | null>(null)
  const [error, setError] = useState("")
  // 本地乐观态：POST 成功后立即折叠为“你的回答：…”。
  const [localAnswer, setLocalAnswer] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  // 同步闸门：state 是异步的，双击/连续 tap 的第二次回调必须在这里被挡住。
  const inFlightRef = useRef(false)
  const answeredRef = useRef(false)

  const resolvedAnswer = localAnswer ?? item.answer ?? ""
  const answered =
    localAnswer !== null || item.answered === true || Boolean(item.answer)
  useEffect(() => {
    if (answered) answeredRef.current = true
  }, [answered])

  // question.requested 事件驱动：挂载时只拉一次 pending 列表确认仍在等
  // 回答（事件本体已带 header/options，无需轮询）。不在 pending 里 →
  // 已被别处处理 → 折叠。网络错误不算已处理。
  const pending = useQuery({
    queryKey: ["questions", runId, item.questionId],
    queryFn: ({ signal }) => api.listQuestions(runId, signal),
    enabled: !answered && !stale,
    staleTime: 0,
    refetchInterval: false,
    refetchOnWindowFocus: false,
    retry: 0,
  })
  useEffect(() => {
    if (answered || stale || !pending.isSuccess) return
    const found = pending.data.questions.some(
      (row) => row.question_id === item.questionId,
    )
    if (!found) setStale(true)
  }, [answered, stale, pending.isSuccess, pending.data, item.questionId])

  if (stale) {
    return (
      <p
        data-question-id={item.questionId}
        data-question-stale="1"
        className="truncate text-xs text-muted"
      >
        {item.header || item.prompt} · 已被处理
      </p>
    )
  }
  if (answered) {
    const label =
      answerLabel(item.options, resolvedAnswer) || resolvedAnswer || "已提交"
    return (
      <p
        data-question-id={item.questionId}
        data-question-answered="1"
        className="truncate text-xs text-muted"
        title={`你的回答：${label}`}
      >
        {item.header || item.prompt} · 你的回答：{label}
      </p>
    )
  }

  const submit = async (rawValue: string) => {
    // 提交的永远是“恰好一个值”：被点中的 option.value（自由输入则是 draft）。
    const text = typeof rawValue === "string" ? rawValue : ""
    if (!text.trim()) return
    if (inFlightRef.current || answeredRef.current) return
    if (!beginQuestionAnswer(item.questionId)) {
      if (isQuestionAnswered(item.questionId)) setError("此问题已回答，无需重复提交")
      return
    }
    inFlightRef.current = true
    setSubmitting(true)
    setPendingValue(text)
    setError("")
    let keepAnswered = true
    try {
      await api.answerQuestion(runId, {
        question_id: item.questionId,
        answer: text,
      })
      answeredRef.current = true
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
            keepAnswered = false
            setError("问题状态已变化，请重试")
          } else {
            answeredRef.current = true
            setStale(true)
          }
        } catch {
          keepAnswered = false
          setError("提交失败，可重试")
        }
      } else {
        keepAnswered = false
        setError("提交失败，可重试")
      }
    } finally {
      finishQuestionAnswer(item.questionId, keepAnswered)
      inFlightRef.current = false
      setSubmitting(false)
      setPendingValue(null)
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
      aria-label={item.header || "需要你回答的问题"}
    >
      {item.header ? (
        <p className="text-sm font-semibold">{item.header}</p>
      ) : null}
      {item.prompt ? (
        <p className="mt-1 whitespace-pre-wrap text-sm">{item.prompt}</p>
      ) : null}
      {options.length > 0 ? (
        <ol
          className="mt-2 list-none space-y-1.5 pl-0"
          aria-label="选项（单选，点击即提交）"
        >
          {options.map((option) => {
            const isPending = pendingValue === option.value
            return (
              <li key={option.key} className="w-full">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="flex w-full items-start justify-start gap-2 whitespace-normal py-1.5 text-left"
                  disabled={submitting}
                  aria-busy={isPending || undefined}
                  aria-label={`选项 ${option.index}：${option.label}`}
                  data-option-index={option.index}
                  data-option-value={option.value}
                  onClick={() => void submit(option.value)}
                >
                  <span
                    aria-hidden="true"
                    className="w-5 shrink-0 text-right tabular-nums text-muted"
                  >
                    {option.index}.
                  </span>
                  <span className="min-w-0 flex-1">{option.label}</span>
                  {isPending ? (
                    <span
                      role="status"
                      className="ml-auto shrink-0 text-xs text-muted"
                    >
                      提交中…
                    </span>
                  ) : null}
                </Button>
              </li>
            )
          })}
        </ol>
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
