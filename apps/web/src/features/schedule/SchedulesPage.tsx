import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "react-router"

import { Button } from "../../components/ui/button"
import { IconClose, IconSpinner } from "../../components/icons"
import { useI18n } from "../../lib/i18n"
import {
  createClient,
  type Schedule,
  type ScheduleExecution,
  type ScheduleRule,
} from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { useAuth } from "../auth/useAuth"

const api = createClient()

const WEEKDAY_NAMES = ["日", "一", "二", "三", "四", "五", "六"]

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

// ---- 创建 / 编辑弹窗 -------------------------------------------------------

function ScheduleEditor({
  schedule,
  onClose,
}: {
  schedule: Schedule | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: ({ signal }) => api.listProjects(signal),
  })
  const [projectId, setProjectId] = useState(schedule?.project_id ?? "")
  const sessions = useQuery({
    queryKey: ["sessions", "project", projectId],
    queryFn: ({ signal }) =>
      api.listSessions({ project_id: projectId || undefined, limit: 50 }, signal),
    enabled: Boolean(projectId),
  })
  const [sessionId, setSessionId] = useState(schedule?.session_id ?? "")
  const [name, setName] = useState(schedule?.name ?? "")
  const [message, setMessage] = useState(schedule?.message ?? "")
  const [kind, setKind] = useState<ScheduleRule["kind"]>(schedule?.rule.kind ?? "interval")
  const [every, setEvery] = useState(
    schedule?.rule.kind === "interval" ? schedule.rule.every : 30,
  )
  const [unit, setUnit] = useState<"minutes" | "hours" | "days">(
    schedule?.rule.kind === "interval" ? schedule.rule.unit : "minutes",
  )
  const [atTime, setAtTime] = useState(
    schedule?.rule.kind === "at" ? schedule.rule.time : "09:00",
  )
  const [weekdays, setWeekdays] = useState<number[]>(
    schedule?.rule.kind === "weekly" ? schedule.rule.weekdays : [1],
  )
  const [weeklyTime, setWeeklyTime] = useState(
    schedule?.rule.kind === "weekly" ? schedule.rule.time : "09:00",
  )
  const [timezone, setTimezone] = useState(
    schedule?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  )
  const [notify, setNotify] = useState(schedule?.notify ?? true)
  const [error, setError] = useState("")

  const rule: ScheduleRule = useMemo(() => {
    if (kind === "interval") return { kind: "interval", every, unit }
    if (kind === "weekly") return { kind: "weekly", weekdays, time: weeklyTime }
    return { kind: "at", time: atTime, once: true }
  }, [kind, every, unit, weekdays, weeklyTime, atTime])

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name.trim() || undefined,
        message: message.trim(),
        rule,
        timezone,
        notify,
      }
      return schedule
        ? api.patchSchedule(schedule.id, { ...body, expected_revision: schedule.revision })
        : api.createSchedule({
            ...body,
            project_id: projectId,
            session_id: sessionId,
            permission_profile: "confirm",
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
  const projectList = (projects.data ?? []).filter((p) => p.is_default || true)
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
    >
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-4 shadow-xl">
        <div className="flex items-center justify-between">
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
        <div className="mt-3 space-y-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="名称（可选）"
            className={input}
          />
          {!schedule ? (
            <>
              <select
                value={projectId}
                onChange={(e) => {
                  setProjectId(e.target.value)
                  setSessionId("")
                }}
                className={input}
                aria-label="项目"
              >
                <option value="">选择项目…</option>
                {projectList.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <select
                value={sessionId}
                onChange={(e) => setSessionId(e.target.value)}
                className={input}
                aria-label="会话"
                disabled={!projectId}
              >
                <option value="">选择会话…</option>
                {sessionList.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title || "未命名会话"}
                  </option>
                ))}
              </select>
            </>
          ) : null}
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="到点要执行的消息…"
            rows={3}
            className={input}
          />
          <div className="flex gap-2">
            {(["interval", "weekly", "at"] as const).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setKind(k)}
                className={
                  "rounded-full px-3 py-1 text-xs " +
                  (kind === k ? "bg-foreground text-background" : "border border-border text-muted")
                }
              >
                {k === "interval" ? "间隔" : k === "weekly" ? "每周" : "定时"}
              </button>
            ))}
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
              />
              <select
                value={unit}
                onChange={(e) => setUnit(e.target.value as typeof unit)}
                className="rounded-md border border-border bg-background px-2 py-1.5"
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
              />
            </div>
          ) : (
            <input
              type="datetime-local"
              value={atTime.length === 5 ? `${new Date().toISOString().slice(0, 10)}T${atTime}` : atTime}
              onChange={(e) => setAtTime(e.target.value)}
              className={input}
            />
          )}
          <input
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            placeholder="时区（如 Asia/Shanghai）"
            className={input}
            aria-label="时区"
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={notify}
              onChange={(e) => setNotify(e.target.checked)}
            />
            完成时通知我
          </label>
          {error ? (
            <p role="alert" className="text-sm text-failure">
              {error}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
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
              {save.isPending ? "保存中…" : "保存"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---- 详情抽屉（执行历史） --------------------------------------------------

function ScheduleDrawer({ schedule, onClose }: { schedule: Schedule; onClose: () => void }) {
  const { t } = useI18n()
  const executions = useQuery({
    queryKey: ["schedule-executions", schedule.id],
    queryFn: ({ signal }) => api.listScheduleExecutions(schedule.id, {}, signal),
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
        <h4 className="mt-4 text-xs font-medium uppercase tracking-wide text-muted">
          执行历史
        </h4>
        {executions.isPending ? (
          <p className="mt-2 text-sm text-muted">{t("app.loading")}</p>
        ) : items.length === 0 ? (
          <p className="mt-2 text-sm text-muted">还没有执行记录</p>
        ) : (
          <ul className="mt-2 space-y-1">
            {items.map((exec: ScheduleExecution) => (
              <li
                key={exec.id}
                className="rounded-md border border-border px-3 py-2 text-sm"
              >
                <div className="flex items-center justify-between">
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
                      ? "已执行"
                      : exec.status === "skipped_busy"
                        ? "跳过（运行中）"
                        : exec.status}
                  </span>
                </div>
                {exec.run_id ? (
                  <Link to={`/runs/${exec.run_id}`} className="mt-1 block text-xs text-muted underline">
                    查看运行
                  </Link>
                ) : exec.reason ? (
                  <p className="mt-1 text-xs text-muted">{exec.reason}</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

// ---- 列表页 ---------------------------------------------------------------

export function SchedulesPage() {
  const auth = useAuth()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<"active" | "paused" | "all">("active")
  const [editing, setEditing] = useState<Schedule | null | "new">(null)
  const [detail, setDetail] = useState<Schedule | null>(null)
  const [error, setError] = useState("")

  const schedules = useQuery({
    queryKey: ["schedules", filter],
    queryFn: ({ signal }) => api.listSchedules({ filter }, signal),
    enabled: auth.status === "authed",
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
      api.runScheduleNow(s.id, { allow_billable: true, expected_revision: s.revision }),
    onSuccess: invalidate,
    onError: (err) => setError(apiErrorText(err)),
  })
  const remove = useMutation({
    mutationFn: (s: Schedule) => api.deleteSchedule(s.id),
    onSuccess: () => {
      invalidate()
      setDetail(null)
    },
    onError: (err) => setError(apiErrorText(err)),
  })

  if (auth.status !== "authed") {
    return (
      <p className="px-6 py-8 text-sm text-muted">
        登录后可管理定时任务。 <Link className="underline" to="/login">登录</Link>
      </p>
    )
  }

  const items = schedules.data?.schedules ?? []

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t("schedule.title")}</h2>
        <Button size="sm" onClick={() => setEditing("new")}>
          {t("schedule.new")}
        </Button>
      </div>
      <div className="mt-4 flex gap-1" role="tablist">
        {(
          [
            ["active", "进行中"],
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
                    {ruleText(s.rule)} · {t("schedule.next")} {fmtTime(s.next_fire)}
                  </span>
                </button>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={runNow.isPending}
                    onClick={() => runNow.mutate(s)}
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
                    onClick={() => {
                      if (window.confirm("删除该定时任务？")) remove.mutate(s)
                    }}
                  >
                    删除
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {editing ? (
        <ScheduleEditor
          schedule={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      ) : null}
      {detail ? <ScheduleDrawer schedule={detail} onClose={() => setDetail(null)} /> : null}
    </div>
  )
}
