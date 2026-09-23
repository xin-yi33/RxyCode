import {
  AlertTriangle,
  Bot,
  Check,
  ChevronDown,
  CircleDashed,
  FileText,
  Terminal,
  X
} from 'lucide-react'
import { useEffect, useRef } from 'react'
import PlanDocumentCard from './PlanDocumentCard'
import type { TeamEventRecord, TimelineItem } from '../lib/conversationStore.mts'
import { looksLikePlanDocument, parsePlanDocument, type PlanDocument } from '../lib/planDocument.mts'
import { hasLaterPlanFinal } from '../lib/planTimeline.mts'
import { shouldShowStartupProgress, visibleRunProgress } from '../lib/taskPresentation.mts'
import { PreviewGallery } from '../../../features/preview/previewGallery.ts'
import { artifactsFromTool, toolSourceLabel } from '../../../features/preview/previewArtifacts.ts'
import { useI18n } from '../../../i18n/I18nContext.tsx'

interface ChatAreaProps {
  timeline: TimelineItem[]
  running: boolean
  error: string | null
  progress?: string | null
  onOpenInspector?: (item: TimelineItem) => void
  activePlan?: { itemId: string; document: PlanDocument; showActions: boolean } | null
  onBuildPlan?: () => void
  onRevisePlan?: (feedback: string) => void
  onSkipPlan?: () => void
  teamEvents?: readonly TeamEventRecord[]
}

function ToolActivity({ item, onOpenInspector }: {
  item: Extract<TimelineItem, { kind: 'tool_activity' }>
  onOpenInspector?: (item: TimelineItem) => void
}): React.JSX.Element {
  const isRunning = item.status === 'running'
  const isRecovering = item.status === 'recovering'
  const verb = isRecovering ? '工具调用遇到问题，正在自动恢复' : isRunning ? '正在运行' : item.status === 'ok' ? '运行了' : '运行失败'
  return (
    <details className={`activity-row tool-activity ${item.status}`} data-testid={`timeline-tool-${item.callId}`}>
      <summary className="activity-summary">
        {isRunning || isRecovering ? <CircleDashed className="activity-spinner" aria-hidden="true" size={15} /> : item.status === 'ok' ? <Check aria-hidden="true" size={15} /> : <X aria-hidden="true" size={15} />}
        <span className="activity-label">{verb} {item.toolName}</span>
        <span className="tool-source" data-tool-source={toolSourceLabel(item.toolName)}>{toolSourceLabel(item.toolName)}</span>
        {item.summary !== undefined && <span className="activity-result">· {item.summary}</span>}
        <ChevronDown className="activity-chevron" aria-hidden="true" size={14} />
      </summary>
      <div className="activity-details">
        <button type="button" className="activity-inspect-button" onClick={() => onOpenInspector?.(item)}>
          <Terminal aria-hidden="true" size={14} />
          查看工具详情
        </button>
        <dl className="activity-detail-list">
          <div><dt>工具</dt><dd>{item.toolName}</dd></div>
          <div><dt>调用 ID</dt><dd>{item.callId}</dd></div>
          {item.arguments !== undefined && <div><dt>参数</dt><dd><pre>{JSON.stringify(item.arguments, null, 2)}</pre></dd></div>}
          {item.summary !== undefined && <div><dt>结果摘要</dt><dd>{item.summary}</dd></div>}
        </dl>
        <PreviewGallery artifacts={artifactsFromTool(item.toolName, item.arguments)} />
      </div>
    </details>
  )
}

function RecoveryActivity({ item, onOpenInspector }: {
  item: Extract<TimelineItem, { kind: 'recovery' }>
  onOpenInspector?: (item: TimelineItem) => void
}): React.JSX.Element {
  const resolved = item.state === 'recovered'
  const exhausted = item.state === 'exhausted'
  const label = exhausted
    ? `自动恢复失败 · 已尝试 ${item.attempts} 次`
    : resolved
      ? `遇到问题并已自动恢复 · ${item.attempts} 次尝试`
      : '工具调用遇到问题，正在自动恢复'
  return (
    <details className={`activity-row recovery-activity ${item.state}`} open={exhausted} data-testid={`timeline-recovery-${item.recoveryId}`}>
      <summary className="activity-summary" onClick={() => onOpenInspector?.(item)}>
        {exhausted ? <X aria-hidden="true" size={15} /> : resolved ? <Check aria-hidden="true" size={15} /> : <CircleDashed className="activity-spinner" aria-hidden="true" size={15} />}
        <span className="activity-label">{label}</span>
        {!exhausted && <ChevronDown className="activity-chevron" aria-hidden="true" size={14} />}
      </summary>
      <div className="activity-details recovery-details">
        <p className="activity-muted">恢复方式：{item.recoveryKind}</p>
        <p className="activity-muted">错误类型：{item.errorKind}</p>
        {item.summary !== undefined && <p>{item.summary}</p>}
        {item.details.length > 0 && (
          <ul>{item.details.map((detail, index) => <li key={`${item.recoveryId}-${index}`}>{detail}</li>)}</ul>
        )}
      </div>
    </details>
  )
}

function TimelineEntry({
  item,
  timeline,
  onOpenInspector,
  activePlan,
  running,
  onBuildPlan,
  onRevisePlan,
  onSkipPlan
}: {
  item: TimelineItem
  timeline: TimelineItem[]
  onOpenInspector?: (item: TimelineItem) => void
  activePlan?: ChatAreaProps['activePlan']
  running: boolean
  onBuildPlan?: () => void
  onRevisePlan?: (feedback: string) => void
  onSkipPlan?: () => void
}): React.JSX.Element {
  switch (item.kind) {
    case 'user_prompt':
      return <article className="timeline-prompt"><div className="timeline-eyebrow">你</div><p>{item.text}</p></article>
    case 'assistant_text':
      if (item.text === '') return <></>
      if (looksLikePlanDocument(item.text)) {
        if (hasLaterPlanFinal(timeline, item.id)) return <></>
        return (
          <PlanDocumentCard
            document={parsePlanDocument(item.text)}
            showActions={false}
            disabled={running}
            onBuild={() => onBuildPlan?.()}
            onRevise={(feedback) => onRevisePlan?.(feedback)}
            onSkip={() => onSkipPlan?.()}
          />
        )
      }
      if (timeline.slice(timeline.findIndex((entry) => entry.id === item.id) + 1).some(
        (entry) => entry.kind === 'final_answer' && entry.text.trim() === item.text.trim()
      )) {
        return <></>
      }
      return <article className="timeline-assistant"><div className="timeline-eyebrow">RxyCode</div><div className="timeline-prose">{item.text}</div></article>
    case 'tool_activity':
      return <ToolActivity item={item} onOpenInspector={onOpenInspector} />
    case 'recovery':
      return <RecoveryActivity item={item} onOpenInspector={onOpenInspector} />
    case 'child_agent':
      return (
        <button type="button" className={`activity-row child-activity state-${item.state}`} onClick={() => onOpenInspector?.(item)} data-testid={`timeline-child-${item.sessionId}`}>
          <Bot aria-hidden="true" size={15} />
          <span className="activity-label">@{item.agentId} · {item.title}</span>
          <span className="activity-result">{item.state === 'running' ? '正在运行' : item.state}</span>
          {item.state === 'running' ? <CircleDashed className="activity-spinner" aria-hidden="true" size={14} /> : <ChevronDown aria-hidden="true" size={14} />}
        </button>
      )
    case 'approval':
      return <button type="button" className="activity-row approval-activity" onClick={() => onOpenInspector?.(item)}><AlertTriangle aria-hidden="true" size={15} /><span className="activity-label">等待审批 · {item.action}</span></button>
    case 'final_answer':
      if (looksLikePlanDocument(item.text)) {
        return (
          <PlanDocumentCard
            document={parsePlanDocument(item.text)}
            showActions={Boolean(activePlan?.showActions && activePlan.itemId === item.id)}
            disabled={running}
            onBuild={() => onBuildPlan?.()}
            onRevise={(feedback) => onRevisePlan?.(feedback)}
            onSkip={() => onSkipPlan?.()}
          />
        )
      }
      return <article className={`final-answer status-${item.status}`} data-testid="final-answer"><div className="final-answer-heading"><FileText aria-hidden="true" size={16} /><span>Final Answer</span></div><div className="timeline-prose">{item.text}</div></article>
    case 'error':
      return <article className="timeline-error" role="alert"><X aria-hidden="true" size={15} /><span>{item.text}</span></article>
  }
}

function ChatArea({
  timeline,
  running,
  error,
  progress,
  onOpenInspector,
  activePlan = null,
  onBuildPlan,
  onRevisePlan,
  onSkipPlan,
  teamEvents = []
}: ChatAreaProps): React.JSX.Element {
  const { t } = useI18n()
  const scrollRef = useRef<HTMLElement | null>(null)
  const stickToBottomRef = useRef(true)
  const runProgress = visibleRunProgress({ progress, timelineLength: timeline.length })

  useEffect(() => {
    const el = scrollRef.current
    if (el !== null && stickToBottomRef.current) el.scrollTop = el.scrollHeight
  }, [timeline, running, error])

  return (
    <section
      className="chat-area"
      ref={scrollRef}
      aria-live="polite"
      onScroll={(event) => {
        const target = event.currentTarget
        stickToBottomRef.current = target.scrollHeight - target.scrollTop - target.clientHeight < 48
      }}
    >
      {timeline.length === 0 ? (
        <div className="chat-empty">
          <p className="chat-empty-hero">{t('emptyChatGreeting')}</p>
          {shouldShowStartupProgress({
            timelineLength: 0,
            running,
            progress
          }) && (
            <div className="task-startup-status" data-testid="task-startup-status">
              <CircleDashed className="activity-spinner" aria-hidden="true" size={14} />
              {progress}
            </div>
          )}
        </div>
      ) : (
        <div className="timeline" data-testid="task-timeline">
          {teamEvents.length > 0 ? (
            <aside className="chat-team-lane" data-testid="chat-team-lane">
              <p className="chat-team-lane-title">{t('teamHubGallery')}</p>
              <ol>
                {teamEvents.slice(-8).map((event, index) => (
                  <li key={`${event.role}-${event.phase}-${index}`}>
                    <strong>{event.role || 'team'}</strong>
                    {event.stage !== '' ? <span> · {event.stage}</span> : null}
                    {event.phase !== '' ? <span> · {event.phase}</span> : null}
                    {event.detail !== '' ? <small>{event.detail}</small> : null}
                  </li>
                ))}
              </ol>
            </aside>
          ) : null}
          {timeline.map((item) => (
            <TimelineEntry
              key={item.id}
              item={item}
              timeline={timeline}
              onOpenInspector={onOpenInspector}
              activePlan={activePlan}
              running={running}
              onBuildPlan={onBuildPlan}
              onRevisePlan={onRevisePlan}
              onSkipPlan={onSkipPlan}
            />
          ))}
          {running && timeline.at(-1)?.kind !== 'tool_activity' && (
            <div className="running-indicator" data-testid="running-indicator" data-phase={timeline.length <= 2 ? 'startup' : 'working'}>
              <CircleDashed className="activity-spinner" aria-hidden="true" size={15} />
              {runProgress ?? (timeline.length <= 2 ? '正在启动 Agent…' : '正在处理')}
            </div>
          )}
        </div>
      )}
      {error !== null && timeline.at(-1)?.kind !== 'error' && <div className="error-banner" role="alert">{error}</div>}
    </section>
  )
}

export default ChatArea
