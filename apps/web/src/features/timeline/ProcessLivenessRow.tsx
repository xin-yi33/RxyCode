import type { TimelineItem } from "../runs/eventReducer"

type LivenessItem = Extract<TimelineItem, { kind: "liveness" }>

const ACTION_LABEL: Record<LivenessItem["action"], string> = {
  continue: "继续运行",
  stop: "建议停止",
  unknown: "无法判定",
}

const ACTION_TONE: Record<LivenessItem["action"], string> = {
  continue: "bg-success/15 text-success-ink",
  stop: "bg-failure/15 text-failure-ink",
  unknown: "bg-waiting/15 text-waiting-ink",
}

function seconds(value: number | undefined): string {
  return value === undefined ? "未上报" : `${value.toFixed(1)}s`
}

function percent(value: number | undefined): string {
  return value === undefined ? "未上报" : `${value.toFixed(1)}%`
}

function bytes(value: number | undefined): string {
  if (value === undefined) return "未上报"
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 ** 2).toFixed(1)} MiB`
}

export function ProcessLivenessRow({ item }: { item: LivenessItem }) {
  const processText =
    item.processCount === undefined ? "未上报" : String(item.processCount)
  return (
    <section
      data-process-liveness
      data-probe-id={item.probeId || undefined}
      data-probe-seq={item.probeSeq}
      data-action={item.action}
      className="rounded-lg border border-border bg-sidebar/60 px-3 py-2 text-xs"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 font-medium ${ACTION_TONE[item.action]}`}>
          {ACTION_LABEL[item.action]}
        </span>
        <span className="text-muted-ink">进程判活</span>
        {item.probeSeq !== undefined ? (
          <span className="text-muted-ink">检查点 #{item.probeSeq}</span>
        ) : null}
        {item.pid !== undefined ? (
          <span className="font-mono text-muted-ink">pid {item.pid}</span>
        ) : null}
      </div>
      <p className="mt-1.5 whitespace-pre-wrap break-words text-foreground">
        {item.text}
      </p>
      <p className="mt-1 break-words text-muted-ink">
        已运行 {seconds(item.elapsedSeconds)} · 观察 {seconds(item.observationSeconds)} ·
        CPU {percent(item.cpuStartPercent)} → {percent(item.cpuEndPercent)} · IO{" "}
        {bytes(item.ioStartBytes)} → {bytes(item.ioEndBytes)} · 进程 {processText}
      </p>
      {item.note ? (
        <p className="mt-1 whitespace-pre-wrap break-words text-muted">
          结论：{item.note}
        </p>
      ) : null}
    </section>
  )
}
