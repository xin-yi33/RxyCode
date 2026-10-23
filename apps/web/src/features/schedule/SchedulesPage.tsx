import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useSearchParams } from "react-router"

import { Button } from "../../components/ui/button"
import { IconClose, IconPlus, IconSpinner } from "../../components/icons"
import { useI18n } from "../../lib/i18n"
import {
  createClient,
  type Schedule,
  type ScheduleExecution,
  type ScheduleRule,
} from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { useAuth } from "../auth/useAuth"
import { useModelsCatalog } from "../models/queries"

const api = createClient()

const WEEKDAY_NAMES = ["日", "一", "二", "三", "四", "五", "六"]
const ACTIVE_RUN_STATUSES = new Set(["queued", "pending", "running", "waiting_approval", "waiting"])

function ruleText(rule: ScheduleRule): string {
  if (rule.kind === "interval") {
    const unit = { minutes: "分钟", hours: "小时", days: "天" }[rule.unit]
    return `每 ${rule.every} ${unit}`
  }
  if (rule.kind === "at") {
    return `定时 ${rule.time}${rule.once ? "（一次性）" : ""}`
  }
  if (rule.kind === "weekly") {
    const days = rule.weekdays.map((d) => WEEKDAY_NAMES[d]).join("、")
    return `每周${days} ${rule.time}`
  }
  return JSON.stringify(rule)
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

/** 规则在选定时区下的未来 3 次时间预览（本地预览；保存后以服务端 next_occurrences 为准）。 */
function previewOccurrences(rule: ScheduleRule, timezone: string): string[] {
  const out: string[] = []
  const now = new Date()
  const fmt = (d: Date) =>
    d.toLocaleString(undefined, { timeZone: timezone || undefined, timeZoneName: "short" })
  try {
    if (rule.kind === "interval") {
      const ms =
        rule.every *
        { minutes: 60_000, hours: 3_600_000, days: 86_400_000 }[rule.unit]
      for (let i = 1; i <= 3; i++) out.push(fmt(new Date(now.getTime() + ms * i)))
      return out
    }
    if (rule.kind === "at") {
      const d = new Date(rule.time.length === 5 ? `${new Date().toISOString().slice(0, 10)}T${rule.time}` : rule.time)
      if (!Number.isNaN(d.getTime())) out.push(fmt(d))
      return out
    }
    if (rule.kind === "weekly") {
      const [hh, mm] = rule.time.split(":").map(Number)
      const cursor = new Date(now)
      for (let guard = 0; guard < 14 && out.length < 3; guard++) {
        cursor.setDate(cursor.getDate() + 1)
        if (rule.weekdays.includes(cursor.getDay())) {
          const d = new Date(cursor)
          d.setHours(hh, mm, 0, 0)
          if (d.getTime() > now.getTime()) out.push(fmt(d))
        }
      }
      return out
    }
  } catch {
    return []
  }
  return out
}

/** SCH-05 推荐模板 —— 只预填表单，不自动执行/发送。 */
const TEMPLATES: { title: string; blurb: string; message: string; rule: ScheduleRule }[] = [
  {
    title: "每周六推荐周末读物",
    blurb: "每周六上午生成一份阅读清单",
    message: "为我推荐本周末的三本读物，附简短理由。",
    rule: { kind: "weekly", weekdays: [6], time: "09:00" },
  },
  {
    title: "每天监测关注商品价格",
    blurb: "每天早晨检查一次目标商品价格",
    message: "检查我关注的商品价格变化并汇报。",
    rule: { kind: "interval", every: 1, unit: "days" },
  },
  {
    title: "每周查找演出",
    blurb: "每周一汇总本周演出信息",
    message: "查找本周同城演出并列一个清单。",
    rule: { kind: "weekly", weekdays: [1], time: "10:00" },
  },
  {
    title: "周四规划周末活动",
    blurb: "每周四下午为周末活动出方案",
    message: "为本周末规划两个活动方案并给出建议。",
    rule: { kind: "weekly", weekdays: [4], time: "15:00" },
  },
]

// ---- 确认弹窗（SCH-09/SCH-10）：明确取消/确认两个出口 ---------------------

function ConfirmDialog({
  title,
  body,
  confirmLabel,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  title: string
  body: string
  confirmLabel: string
  busy: boolean
  error: string
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useI18n()
  return (
    <div
      role="presentation"
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        className="w-full max-w-sm rounded-xl border border-border bg-card p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="mt-2 text-sm text-muted">{body}</p>
        {error ? (
          <p role="alert" className="mt-2 text-xs text-failure">
            {error}
          </p>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            autoFocus
            className="rounded-md border border-border px-3 py-1.5 text-sm"
            onClick={onCancel}
          >
            {t("app.cancel")}
          </button>
          <button
            type="button"
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-ink disabled:opacity-60"
            disabled={busy}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---- 创建 / 编辑弹窗（SCH-02/03/05/08）：完整字段表单 ----------------------

type EditorDraft = {
  name: string
  message: string
  projectId: string
  sessionId: string
  rule: ScheduleRule
}

function ScheduleEditor({
  schedule,
  draft,
  onClose,
}: {
  schedule: Schedule | null
  draft: EditorDraft | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const catalog = useModelsCatalog(true)
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: ({ signal }) => api.listProjects(signal),
  })
  const [projectId, setProjectId] = useState(
    schedule?.project_id ?? draft?.projectId ?? "",
  )
  const sessions = useQuery({
    queryKey: ["sessions", "project", projectId],
    queryFn: ({ signal }) =>
      api.listSessions({ project_id: projectId || undefined, limit: 50 }, signal),
    enabled: Boolean(projectId),
  })
  const [sessionId, setSessionId] = useState(schedule?.session_id ?? draft?.sessionId ?? "")
  const [name, setName] = useState(schedule?.name ?? draft?.name ?? "")
  const [message, setMessage] = useState(schedule?.message ?? draft?.message ?? "")
  const initialRule = schedule?.rule ?? draft?.rule ?? null
  const [kind, setKind] = useState<ScheduleRule["kind"]>(initialRule?.kind ?? "interval")
  const [every, setEvery] = useState(
    initialRule?.kind === "interval" ? initialRule.every : 30,
  )
  const [unit, setUnit] = useState<"minutes" | "hours" | "days">(
    initialRule?.kind === "interval" ? initialRule.unit : "minutes",
  )
  const [atTime, setAtTime] = useState(initialRule?.kind === "at" ? initialRule.time : "09:00")
  const [weekdays, setWeekdays] = useState<number[]>(
    initialRule?.kind === "weekly" ? initialRule.weekdays : [1],
  )
  const [weeklyTime, setWeeklyTime] = useState(
    initialRule?.kind === "weekly" ? initialRule.time : "09:00",
  )
  const [timezone, setTimezone] = useState(
    schedule?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  )
  const models = catalog.data?.models ?? []
  const defaultRef = catalog.data?.default_model_ref ?? ""
  const [modelRef, setModelRef] = useState(schedule?.model_ref ?? "")
  const [permission, setPermission] = useState(
    schedule?.permission_profile === "full" ? "full" : "confirm",
  )
  const [notify, setNotify] = useState(schedule?.notify ?? true)
  const [enabled, setEnabled] = useState(schedule?.enabled ?? true)
  const [requestId] = useState(() => crypto.randomUUID())
  const [error, setError] = useState("")

  const rule: ScheduleRule = useMemo(() => {
    if (kind === "interval") return { kind: "interval", every, unit }
    if (kind === "weekly") return { kind: "weekly", weekdays, time: weeklyTime }
    return { kind: "at", time: atTime, once: true }
  }, [kind, every, unit, weekdays, weeklyTime, atTime])

  const preview = previewOccurrences(rule, timezone)
  // SCH-14：无可用模型时给出修复入口而不是假保存。
  const noModelAvailable =
    catalog.isSuccess && models.filter((m) => m.status === "available").length === 0

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name.trim() || undefined,
        message: message.trim(),
        rule,
        timezone,
        model_ref: modelRef || null,
        permission_profile: permission,
        notify,
        enabled,
      }
      return schedule
        ? api.patchSchedule(schedule.id, { ...body, expected_revision: schedule.revision })
        : api.createSchedule({
            ...body,
            project_id: projectId,
            session_id: sessionId,
            request_id: requestId,
          })
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["schedules"] })
      onClose()
    },
    onError: (err) => setError(apiErrorText(err)),
  })

  const input =
    "w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
  const label = "mb-1 block text-xs font-medium text-muted"
  const projectList = projects.data ?? []
  const sessionList = sessions.data?.sessions ?? []

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={schedule ? "编辑定时任务" : "新建定时任务"}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose()
      }}
    >
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl border border-border bg-card shadow-xl">
        <div className="flex items-center justify-between border-b border-border p-4">
          <h3 className="text-sm font-semibold">
            {schedule ? "编辑定时任务" : "新建定时任务"}
          </h3>
          <button
            type="button"
            aria-label="关闭"
            className="rounded p-1 text-muted hover:bg-background"
            onClick={onClose}
          >
            <IconClose size={15} />
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
          <div>
            <label className={label} htmlFor="sched-name">
              名称
            </label>
            <input
              id="sched-name"
              value={name}
              maxLength={100}
              onChange={(e) => setName(e.target.value)}
              className={input}
            />
          </div>
          {!schedule ? (
            <>
              <div>
                <label className={label} htmlFor="sched-project">
                  归属项目 *
                </label>
                <select
                  id="sched-project"
                  value={projectId}
                  onChange={(e) => {
                    setProjectId(e.target.value)
                    setSessionId("")
                  }}
                  className={input}
                >
                  <option value="">选择项目…</option>
                  {projectList.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={label} htmlFor="sched-session">
                  归属会话 *
                </label>
                <select
                  id="sched-session"
                  value={sessionId}
                  onChange={(e) => setSessionId(e.target.value)}
                  className={input}
                  disabled={!projectId}
                >
                  <option value="">选择会话…</option>
                  {sessionList.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.title || "未命名会话"}
                    </option>
                  ))}
                </select>
              </div>
            </>
          ) : null}
          <div>
            <label className={label} htmlFor="sched-message">
              要执行的内容 *
            </label>
            <textarea
              id="sched-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={3}
              className={input}
            />
          </div>
          <div>
            <span className={label}>频率 *</span>
            <div className="flex gap-2" role="radiogroup" aria-label="频率">
              {(["interval", "weekly", "at"] as const).map((k) => (
                <button
                  key={k}
                  type="button"
                  role="radio"
                  aria-checked={kind === k}
                  onClick={() => setKind(k)}
                  className={
                    "rounded-full px-3 py-1 text-xs " +
                    (kind === k ? "bg-foreground text-background" : "border border-border text-muted")
                  }
                >
                  {k === "interval" ? "间隔" : k === "weekly" ? "每周" : "一次性"}
                </button>
              ))}
            </div>
          </div>
          {kind === "interval" ? (
            <div className="flex items-center gap-2 text-sm">
              每
              <input
                type="number"
                min={1}
                value={every}
                onChange={(e) => setEvery(Math.max(1, Number(e.target.value) || 1))}
                className="w-20 rounded-md border border-border bg-background px-2 py-1.5"
                aria-label="间隔数值"
              />
              <select
                value={unit}
                onChange={(e) => setUnit(e.target.value as typeof unit)}
                className="rounded-md border border-border bg-background px-2 py-1.5"
                aria-label="间隔单位"
              >
                <option value="minutes">分钟</option>
                <option value="hours">小时</option>
                <option value="days">天</option>
              </select>
            </div>
          ) : kind === "weekly" ? (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-1">
                {WEEKDAY_NAMES.map((d, i) => (
                  <button
                    key={i}
                    type="button"
                    aria-pressed={weekdays.includes(i)}
                    onClick={() =>
                      setWeekdays((prev) =>
                        prev.includes(i) ? prev.filter((x) => x !== i) : [...prev, i].sort(),
                      )
                    }
                    className={
                      "h-7 w-7 rounded-full text-xs " +
                      (weekdays.includes(i)
                        ? "bg-foreground text-background"
                        : "border border-border text-muted")
                    }
                  >
                    {d}
                  </button>
                ))}
              </div>
              <input
                type="time"
                value={weeklyTime}
                onChange={(e) => setWeeklyTime(e.target.value)}
                className={input}
                aria-label="执行时间"
              />
            </div>
          ) : (
            <input
              type="datetime-local"
              value={atTime.length === 5 ? `${new Date().toISOString().slice(0, 10)}T${atTime}` : atTime}
              onChange={(e) => setAtTime(e.target.value)}
              className={input}
              aria-label="执行时间"
            />
          )}
          <div>
            <label className={label} htmlFor="sched-tz">
              时区 *
            </label>
            <input
              id="sched-tz"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className={input}
            />
            {preview.length ? (
              <p className="mt-1 text-xs text-muted">
                未来时间：{preview.join("；")}
              </p>
            ) : null}
          </div>
          <div>
            <label className={label} htmlFor="sched-model">
              模型
            </label>
            <select
              id="sched-model"
              value={modelRef}
              onChange={(e) => setModelRef(e.target.value)}
              className={input}
            >
              <option value="">
                跟随默认{defaultRef ? `（${defaultRef}）` : ""}
              </option>
              {models.map((m) => (
                <option key={m.model_ref} value={m.model_ref} disabled={m.status !== "available"}>
                  {m.provider_name} · {m.display_name}
                  {m.status !== "available" ? "（不可用）" : ""}
                </option>
              ))}
            </select>
            {noModelAvailable ? (
              <p className="mt-1 text-xs text-failure">
                没有可用模型，请先到{" "}
                <Link className="underline" to="/settings/addmodel">
                  模型设置
                </Link>{" "}
                添加。
              </p>
            ) : null}
          </div>
          <div>
            <label className={label} htmlFor="sched-perm">
              权限
            </label>
            <select
              id="sched-perm"
              value={permission}
              onChange={(e) => setPermission(e.target.value as "confirm" | "full")}
              className={input}
            >
              <option value="confirm">confirm — 危险操作需审批</option>
              <option value="full">full — 全自动（受云沙箱限制）</option>
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={notify}
              onChange={(e) => setNotify(e.target.checked)}
            />
            执行完成后发送结果邮件
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            启用（取消勾选则保存为暂停）
          </label>
          {error ? (
            <p role="alert" className="text-sm text-failure">
              {error}
            </p>
          ) : null}
        </div>
        <div className="flex justify-end gap-2 border-t border-border p-4">
          <Button variant="outline" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button
            size="sm"
            disabled={
              save.isPending ||
              !message.trim() ||
              (!schedule && (!projectId || !sessionId)) ||
              (kind === "weekly" && weekdays.length === 0)
            }
            onClick={() => save.mutate()}
          >
            {save.isPending ? "保存中…" : "保存定时任务"}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---- 详情抽屉（SCH-06/11/12/13）：规则/历史/投递状态 -----------------------

function ScheduleDrawer({ schedule, onClose }: { schedule: Schedule; onClose: () => void }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [error, setError] = useState("")
  const executions = useQuery({
    queryKey: ["schedule-executions", schedule.id],
    queryFn: ({ signal }) => api.listScheduleExecutions(schedule.id, {}, signal),
    refetchInterval: 15_000,
  })
  const retryEmail = useMutation({
    mutationFn: (notificationId: string) => api.retryNotificationEmail(notificationId),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["schedule-executions", schedule.id] }),
    onError: (err) => setError(apiErrorText(err)),
  })
  const stopRun = useMutation({
    mutationFn: (runId: string) => api.cancelRun(runId),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["schedule-executions", schedule.id] }),
    onError: (err) => setError(apiErrorText(err)),
  })
  const items = executions.data?.executions ?? []
  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-label="定时任务详情"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="h-full w-full max-w-md overflow-y-auto border-l border-border bg-card p-4">
        <div className="flex items-center justify-between">
          <h3 className="truncate text-sm font-semibold">{schedule.name || "定时任务"}</h3>
          <button
            type="button"
            aria-label={t("app.close")}
            className="rounded p-1 text-muted hover:bg-background"
            onClick={onClose}
          >
            <IconClose size={15} />
          </button>
        </div>
        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex gap-2">
            <dt className="w-20 shrink-0 text-muted">规则</dt>
            <dd>{ruleText(schedule.rule)}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-20 shrink-0 text-muted">时区</dt>
            <dd>{schedule.timezone}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-20 shrink-0 text-muted">模型</dt>
            <dd>{schedule.model_ref || "跟随默认"}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-20 shrink-0 text-muted">权限</dt>
            <dd>{schedule.permission_profile}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-20 shrink-0 text-muted">{t("schedule.next")}</dt>
            <dd>{fmtTime(schedule.next_fire)}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-20 shrink-0 text-muted">消息</dt>
            <dd className="whitespace-pre-wrap break-words">{schedule.message}</dd>
          </div>
          {schedule.blocked_reason && schedule.blocked_reason !== "none" ? (
            <div className="flex gap-2">
              <dt className="w-20 shrink-0 text-muted">阻塞</dt>
              <dd className="text-failure">{schedule.blocked_reason}</dd>
            </div>
          ) : null}
        </dl>
        {error ? (
          <p role="alert" className="mt-3 text-xs text-failure">
            {error}
          </p>
        ) : null}
        <h4 className="mt-4 text-xs font-medium uppercase tracking-wide text-muted">
          执行历史
        </h4>
        {executions.isPending ? (
          <p className="mt-2 text-sm text-muted">{t("app.loading")}</p>
        ) : items.length === 0 ? (
          <p className="mt-2 text-sm text-muted">还没有执行记录</p>
        ) : (
          <ul className="mt-2 space-y-1">
            {items.map((exec: ScheduleExecution) => {
              const runActive = exec.run_status
                ? ACTIVE_RUN_STATUSES.has(exec.run_status)
                : false
              const emailFailed = exec.email?.status === "failed"
              return (
                <li
                  key={exec.id}
                  className="rounded-md border border-border px-3 py-2 text-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span>{fmtTime(exec.scheduled_for)}</span>
                    <span
                      className={
                        "rounded-full px-2 py-0.5 text-xs " +
                        (exec.status === "fired"
                          ? "bg-success/15 text-success-ink"
                          : exec.status === "skipped_busy"
                            ? "bg-waiting/15 text-waiting-ink"
                            : "bg-failure/15 text-failure-ink")
                      }
                    >
                      {exec.status === "fired"
                        ? runActive
                          ? "执行中"
                          : exec.run_status || "已执行"
                        : exec.status === "skipped_busy"
                          ? "跳过（运行中）"
                          : exec.status}
                    </span>
                  </div>
                  {/* 失败原因就地展开（SCH-11）。 */}
                  {exec.reason ? (
                    <p className="mt-1 text-xs text-failure">{exec.reason}</p>
                  ) : null}
                  {/* 投递状态：站内/邮件 pending|sent|failed，不等同 Agent 成功。 */}
                  {exec.email ? (
                    <p className="mt-1 flex items-center gap-2 text-xs text-muted">
                      结果邮件：
                      {exec.email.status === "sent"
                        ? "已发送"
                        : exec.email.status === "pending"
                          ? "投递中"
                          : "投递失败"}
                      {emailFailed && exec.notification_id ? (
                        <button
                          type="button"
                          className="underline disabled:opacity-60"
                          disabled={retryEmail.isPending}
                          onClick={() => retryEmail.mutate(exec.notification_id!)}
                        >
                          重试邮件
                        </button>
                      ) : null}
                    </p>
                  ) : null}
                  <div className="mt-1 flex items-center gap-3">
                    {exec.run_id ? (
                      <Link
                        to={`/app/s/${schedule.session_id}`}
                        className="text-xs text-muted underline"
                      >
                        查看运行
                      </Link>
                    ) : null}
                    {/* SCH-12：仅运行中可停止本次；不关 schedule。 */}
                    {runActive && exec.run_id ? (
                      <button
                        type="button"
                        className="text-xs text-failure underline disabled:opacity-60"
                        disabled={stopRun.isPending}
                        onClick={() => stopRun.mutate(exec.run_id!)}
                      >
                        停止本次
                      </button>
                    ) : null}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}

// ---- 列表页（SCH-01..10） -------------------------------------------------

export function SchedulesPage() {
  const auth = useAuth()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  // SCH-01：筛选状态写进 URL query，刷新/分享保持。
  const [params, setParams] = useSearchParams()
  const rawFilter = params.get("filter") ?? "enabled"
  const filter: "enabled" | "paused" | "all" =
    rawFilter === "paused" || rawFilter === "all" ? rawFilter : "enabled"
  const setFilter = (value: string) =>
    setParams(value === "enabled" ? {} : { filter: value }, { replace: true })
  const [quickText, setQuickText] = useState("")
  const [showTemplates, setShowTemplates] = useState(false)
  const [editing, setEditing] = useState<Schedule | null | "new">(null)
  const [editorDraft, setEditorDraft] = useState<EditorDraft | null>(null)
  const [detail, setDetail] = useState<Schedule | null>(null)
  const [confirm, setConfirm] = useState<
    | { kind: "run-now"; schedule: Schedule }
    | { kind: "delete"; schedule: Schedule }
    | null
  >(null)
  const [error, setError] = useState("")

  const schedules = useQuery({
    queryKey: ["schedules", filter],
    queryFn: ({ signal }) => api.listSchedules({ filter }, signal),
    enabled: auth.status === "authed",
    refetchInterval: 30_000,
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["schedules"] })
  }

  const toggle = useMutation({
    mutationFn: (s: Schedule) =>
      api.patchSchedule(s.id, { enabled: !s.enabled, expected_revision: s.revision }),
    onSuccess: invalidate,
    onError: (err) => setError(apiErrorText(err)),
  })
  const runNow = useMutation({
    mutationFn: (s: Schedule) =>
      api.runScheduleNow(s.id, {
        allow_billable: true,
        expected_revision: s.revision,
        request_id: crypto.randomUUID(),
      }),
    onSuccess: () => {
      invalidate()
      setConfirm(null)
    },
    onError: (err) => {
      setError(apiErrorText(err))
      setConfirm(null)
    },
  })
  const remove = useMutation({
    mutationFn: (s: Schedule) => api.deleteSchedule(s.id),
    onSuccess: () => {
      invalidate()
      setDetail(null)
      setConfirm(null)
    },
    onError: (err) => {
      setError(apiErrorText(err))
      setConfirm(null)
    },
  })

  const openEditor = (draft?: Partial<EditorDraft>) => {
    setEditorDraft({
      name: draft?.name ?? "",
      message: draft?.message ?? "",
      projectId: draft?.projectId ?? "",
      sessionId: draft?.sessionId ?? "",
      rule: draft?.rule ?? { kind: "interval", every: 1, unit: "days" },
    })
    setEditing("new")
  }

  if (auth.status !== "authed") {
    return (
      <p className="px-6 py-8 text-sm text-muted">
        登录后可管理定时任务。 <Link className="underline" to="/login">登录</Link>
      </p>
    )
  }

  const items = schedules.data?.schedules ?? []

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("schedule.title")}</h2>
          <p className="mt-0.5 text-sm text-muted">
            安排任务，到时由 Agent 执行并发送结果
          </p>
        </div>
        <div className="flex gap-1" role="tablist" aria-label="状态筛选">
          {(
            [
              ["enabled", "已开启"],
              ["paused", "已暂停"],
              ["all", t("app.all")],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={filter === id}
              onClick={() => setFilter(id)}
              className={
                "rounded-full px-3 py-1 text-xs " +
                (filter === id ? "bg-foreground text-background" : "border border-border text-muted")
              }
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* SCH-02/03 输入栏：+ 开空白表单；箭头把原文带入表单，不直接执行。 */}
      <div className="mt-4 flex items-center gap-2 rounded-full border border-border bg-card px-2 py-1.5">
        <button
          type="button"
          aria-label={t("schedule.new")}
          title={t("schedule.new")}
          className="rounded-full p-1.5 text-muted hover:bg-sidebar"
          onClick={() => openEditor()}
        >
          <IconPlus size={16} />
        </button>
        <input
          value={quickText}
          onChange={(e) => setQuickText(e.target.value)}
          placeholder="描述要定时执行的任务…"
          className="min-w-0 flex-1 bg-transparent text-sm outline-none"
          aria-label="定时任务描述"
          onKeyDown={(e) => {
            if (e.key === "Enter" && quickText.trim() && !e.nativeEvent.isComposing) {
              openEditor({ message: quickText.trim(), name: quickText.trim().slice(0, 30) })
            }
          }}
        />
        <button
          type="button"
          aria-label="创建定时任务"
          title="创建定时任务"
          disabled={!quickText.trim()}
          className="rounded-full p-1.5 text-muted hover:bg-sidebar disabled:opacity-40"
          onClick={() =>
            openEditor({ message: quickText.trim(), name: quickText.trim().slice(0, 30) })
          }
        >
          ➤
        </button>
      </div>

      {error ? (
        <p role="alert" className="mt-3 text-sm text-failure">
          {error}
        </p>
      ) : null}
      {schedules.isPending ? (
        <p className="mt-6 flex items-center gap-2 text-sm text-muted">
          <IconSpinner size={15} /> {t("app.loading")}
        </p>
      ) : schedules.isError ? (
        <p role="alert" className="mt-6 text-sm text-failure">
          {apiErrorText(schedules.error)}{" "}
          <button type="button" className="underline" onClick={() => void schedules.refetch()}>
            {t("app.retry")}
          </button>
        </p>
      ) : items.length === 0 ? (
        <p className="mt-6 text-sm text-muted">还没有定时任务</p>
      ) : (
        <ul className="mt-4 space-y-2">
          {items.map((s) => (
            <li
              key={s.id}
              className="rounded-lg border border-border bg-card p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left"
                  onClick={() => setDetail(s)}
                >
                  <span className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium">
                      {s.name || s.message.slice(0, 40) || "定时任务"}
                    </span>
                    <span
                      className={
                        "shrink-0 rounded-full px-2 py-0.5 text-xs " +
                        (s.enabled
                          ? "bg-success/15 text-success-ink"
                          : "bg-border text-muted-ink")
                      }
                    >
                      {s.enabled ? t("schedule.enabled") : t("schedule.paused")}
                    </span>
                  </span>
                  <span className="mt-1 block truncate text-xs text-muted">
                    {ruleText(s.rule)} · {s.timezone} · {t("schedule.next")}{" "}
                    {fmtTime(s.next_fire)}
                    {s.model_ref ? ` · ${s.model_ref}` : ""}
                  </span>
                  {/* 最近结果就地展示：skipped_busy/失败原因可读，不是一颗红点。 */}
                  {s.last_execution ? (
                    <span
                      className={
                        "mt-1 block truncate text-xs " +
                        (s.last_execution.status === "fired"
                          ? "text-muted"
                          : "text-failure")
                      }
                    >
                      最近：
                      {s.last_execution.status === "skipped_busy"
                        ? "跳过（运行中）"
                        : s.last_execution.status}
                      {s.last_execution.reason ? ` — ${s.last_execution.reason}` : ""}
                    </span>
                  ) : null}
                </button>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={runNow.isPending}
                    onClick={() => setConfirm({ kind: "run-now", schedule: s })}
                  >
                    {t("schedule.runNow")}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setEditing(s)}>
                    编辑
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={toggle.isPending}
                    onClick={() => toggle.mutate(s)}
                  >
                    {s.enabled ? "暂停" : "启用"}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={remove.isPending}
                    onClick={() => setConfirm({ kind: "delete", schedule: s })}
                  >
                    删除
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* SCH-04/05 推荐模板：折叠列表；点击只预填表单。 */}
      <div className="mt-8">
        <button
          type="button"
          aria-expanded={showTemplates}
          className="flex items-center gap-1 text-sm font-medium text-muted hover:text-foreground"
          onClick={() => setShowTemplates((v) => !v)}
        >
          <span aria-hidden className="inline-block w-3 text-[10px]">
            {showTemplates ? "▾" : "▸"}
          </span>
          推荐
        </button>
        {showTemplates ? (
          <ul className="mt-2 space-y-1">
            {TEMPLATES.map((tpl) => (
              <li key={tpl.title}>
                <button
                  type="button"
                  className="flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left hover:bg-card"
                  onClick={() =>
                    openEditor({ name: tpl.title, message: tpl.message, rule: tpl.rule })
                  }
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm">{tpl.title}</span>
                    <span className="block truncate text-xs text-muted">{tpl.blurb}</span>
                  </span>
                  <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs text-muted">
                    +
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {editing ? (
        <ScheduleEditor
          schedule={editing === "new" ? null : editing}
          draft={editing === "new" ? editorDraft : null}
          onClose={() => {
            setEditing(null)
            setEditorDraft(null)
          }}
        />
      ) : null}
      {detail ? <ScheduleDrawer schedule={detail} onClose={() => setDetail(null)} /> : null}
      {confirm?.kind === "run-now" ? (
        <ConfirmDialog
          title={t("schedule.runNow")}
          body="立即执行会消耗一次 API 额度，且与正常调度分开记录。确认执行？"
          confirmLabel={t("schedule.runNow")}
          busy={runNow.isPending}
          error=""
          onCancel={() => setConfirm(null)}
          onConfirm={() => runNow.mutate(confirm.schedule)}
        />
      ) : null}
      {confirm?.kind === "delete" ? (
        <ConfirmDialog
          title="删除定时任务"
          body="删除定时任务，已生成的聊天保留。确认删除？"
          confirmLabel={t("app.delete")}
          busy={remove.isPending}
          error=""
          onCancel={() => setConfirm(null)}
          onConfirm={() => remove.mutate(confirm.schedule)}
        />
      ) : null}
    </div>
  )
}
