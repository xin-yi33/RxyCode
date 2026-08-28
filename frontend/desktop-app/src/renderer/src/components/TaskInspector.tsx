import { Bot, Check, ChevronLeft, CircleDashed, FileText, Terminal, X } from 'lucide-react'
import { useState } from 'react'
import type { ChildSessionView, RunState, TimelineItem, UsageSnapshot } from '../lib/conversationStore.mts'
import { formatTokenCount, formatUsageRate } from '../lib/taskPresentation.mts'
import { ReviewScopeSelector } from '../../../features/review/ReviewScopeSelector.ts'
import { type ReviewScope } from '../../../features/review/review.comments.ts'
import { emptyDiffState } from '../../../features/git/diffView.ts'

interface TaskInspectorProps {
  focusItem: TimelineItem | null
  usage: UsageSnapshot
  childSessions: ChildSessionView[]
  onClose: () => void
  onSelectChild?: (sessionId: string) => void
}

function RunStateIcon({ state }: { state: RunState }): React.JSX.Element {
  if (state === 'running' || state === 'queued' || state === 'approval') {
    return <CircleDashed className="activity-spinner" aria-hidden="true" size={16} />
  }
  if (state === 'failed' || state === 'cancelled' || state === 'timed_out') {
    return <X aria-hidden="true" size={16} />
  }
  return <Check aria-hidden="true" size={16} />
}

function UsagePanel({ usage }: { usage: UsageSnapshot }): React.JSX.Element {
  return (
    <section className="inspector-section" data-testid="usage-panel">
      <p className="inspector-eyebrow">MODEL USAGE</p>
      <dl className="usage-list">
        <div><dt>Input</dt><dd>{formatTokenCount(usage.inputTokens)}</dd></div>
        <div><dt>Output</dt><dd>{formatTokenCount(usage.outputTokens)}</dd></div>
        <div><dt>Cache hit</dt><dd>{formatTokenCount(usage.cacheHitTokens)}</dd></div>
        <div><dt>Cache write</dt><dd>{formatTokenCount(usage.cacheWriteTokens)}</dd></div>
        <div><dt>Cache rate</dt><dd>{formatUsageRate(usage)}</dd></div>
      </dl>
      {usage.reportingStatus === 'not_reported' && <p className="inspector-muted">Provider 未上报 token 使用量，不将未知值记为 0。</p>}
    </section>
  )
}

function TaskInspector({ focusItem, usage, childSessions, onClose, onSelectChild }: TaskInspectorProps): React.JSX.Element {
  const [reviewScope, setReviewScope] = useState<ReviewScope>('last_turn')
  const focusedChild = focusItem?.kind === 'child_agent'
    ? childSessions.find((child) => child.sessionId === focusItem.sessionId)
    : undefined
  return (
    <aside className="task-inspector" data-testid="inspector" aria-label="Contextual task inspector">
      <header className="inspector-header">
        <button type="button" className="icon-button" onClick={onClose} aria-label="Close inspector" title="Close inspector"><ChevronLeft aria-hidden="true" size={17} /></button>
        <div><p className="inspector-eyebrow">INSPECTOR</p><h2>{focusItem?.kind === 'child_agent' ? 'Child agent' : focusItem?.kind === 'tool_activity' ? 'Tool activity' : focusItem?.kind === 'recovery' ? 'Automatic recovery' : 'Task usage'}</h2></div>
      </header>
      <div className="inspector-content">
        <section className="inspector-section">
          <p className="inspector-eyebrow">REVIEW SCOPE</p>
          <ReviewScopeSelector value={reviewScope} onChange={setReviewScope} />
          {emptyDiffState() === 'empty' ? (
            <p className="inspector-muted" data-testid="review-diff-empty">No diff on this branch</p>
          ) : null}
        </section>
        {focusItem?.kind === 'child_agent' && (
          <section className="inspector-section child-inspector">
            <div className="inspector-title-row"><Bot aria-hidden="true" size={18} /><strong>@{focusItem.agentId}</strong><span className={`state-${focusItem.state}`}>{focusItem.state}</span></div>
            <p className="inspector-muted">{focusItem.title}</p>
            <dl className="detail-list"><div><dt>Session</dt><dd>{focusItem.sessionId}</dd></div><div><dt>Parent</dt><dd>Current task</dd></div></dl>
            {focusedChild?.events !== undefined && focusedChild.events.length > 0 && (
              <div className="child-timeline" data-testid={`child-timeline-${focusItem.sessionId}`}>
                <p className="inspector-eyebrow">CHILD ACTIVITY</p>
                <ol className="inspector-events">
                  {focusedChild.events.map((event, index) => (
                    <li key={`${focusItem.sessionId}-${event.eventName}-${index}`}>
                      <strong>{event.eventName}</strong>
                      {event.toolName !== undefined && <span> · {event.toolName}</span>}
                      {event.text !== undefined && <p>{event.text}</p>}
                      {event.summary !== undefined && <p>{event.summary}</p>}
                      {event.error !== undefined && <p className="inspector-error">{event.error}</p>}
                    </li>
                  ))}
                </ol>
              </div>
            )}
            <button type="button" className="inspector-primary" onClick={() => onSelectChild?.(focusItem.sessionId)}>Open child timeline</button>
          </section>
        )}
        {focusItem?.kind === 'tool_activity' && (
          <section className="inspector-section">
            <div className="inspector-title-row"><Terminal aria-hidden="true" size={17} /><strong>{focusItem.toolName}</strong><span>{focusItem.status}</span></div>
            <dl className="detail-list"><div><dt>Call ID</dt><dd>{focusItem.callId}</dd></div><div><dt>Status</dt><dd>{focusItem.status}</dd></div></dl>
            {focusItem.arguments !== undefined && <pre className="inspector-code">{JSON.stringify(focusItem.arguments, null, 2)}</pre>}
            {focusItem.summary !== undefined && <p className="inspector-result">{focusItem.summary}</p>}
          </section>
        )}
        {focusItem?.kind === 'recovery' && (
          <section className="inspector-section">
            <div className="inspector-title-row"><CircleDashed aria-hidden="true" size={17} /><strong>{focusItem.state}</strong></div>
            <dl className="detail-list"><div><dt>Method</dt><dd>{focusItem.recoveryKind}</dd></div><div><dt>Attempts</dt><dd>{focusItem.attempts} / {focusItem.maxAttempts}</dd></div><div><dt>Error</dt><dd>{focusItem.errorKind}</dd></div></dl>
            <ul className="inspector-events">{focusItem.details.map((detail, index) => <li key={`${focusItem.recoveryId}-${index}`}>{detail}</li>)}</ul>
          </section>
        )}
        {focusItem?.kind === 'final_answer' && <section className="inspector-section"><div className="inspector-title-row"><FileText aria-hidden="true" size={17} /><strong>Final Answer</strong></div><p className="inspector-muted">{focusItem.status}</p></section>}
        <UsagePanel usage={usage} />
        {childSessions.length > 0 && (
          <section className="inspector-section">
            <p className="inspector-eyebrow">CHILD SESSIONS</p>
            <ul className="inspector-child-list">{childSessions.map((child) => <li key={child.sessionId}><button type="button" onClick={() => onSelectChild?.(child.sessionId)}><RunStateIcon state={child.state} /><span>@{child.agentId}</span><small>{child.state}</small></button></li>)}</ul>
          </section>
        )}
      </div>
    </aside>
  )
}

export default TaskInspector
