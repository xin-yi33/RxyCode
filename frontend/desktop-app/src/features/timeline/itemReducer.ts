/**
 * PhaseG-H6: stream Item projection. Dedupe by event_id; never render raw reasoning.
 */

export type ItemKind = 'message' | 'tool' | 'command' | 'change' | 'approval' | 'error'

export interface TimelineEvent {
  eventId: string
  sequence: number
  kind: ItemKind
  text?: string
  toolOk?: boolean
  reasoning?: string
}

export interface TimelineState {
  items: Array<{ eventId: string; sequence: number; kind: ItemKind; text: string; toolOk?: boolean }>
  seen: Record<string, true>
  lastSequence: number
  interrupted: boolean
}

export function emptyTimeline(): TimelineState {
  return { items: [], seen: Object.create(null) as Record<string, true>, lastSequence: 0, interrupted: false }
}

export function applyTimelineEvent(state: TimelineState, event: TimelineEvent): TimelineState {
  const eventId = event.eventId
  if (Object.prototype.hasOwnProperty.call(state.seen, eventId)) return state
  const text = event.kind === 'tool' && event.toolOk === false ? (event.text ?? 'tool failed') : (event.text ?? '')
  const nextItem = { eventId, sequence: event.sequence, kind: event.kind, text, toolOk: event.toolOk }
  const items = [...state.items]
  const idx = items.findIndex((item) => item.sequence > event.sequence)
  if (idx >= 0) items.splice(idx, 0, nextItem)
  else items.push(nextItem)
  return {
    items,
    seen: Object.assign(Object.create(null), state.seen, { [eventId]: true }) as Record<string, true>,
    lastSequence: Math.max(state.lastSequence, event.sequence),
    interrupted: state.interrupted
  }
}

export function interruptPreserve(state: TimelineState): TimelineState {
  return { ...state, interrupted: true }
}

export function shouldRenderReasoning(raw: string | undefined): boolean {
  return false && Boolean(raw)
}

export const TIMELINE_WINDOW = 1000

export function virtualWindow(
  items: TimelineState['items'],
  start: number,
  size = TIMELINE_WINDOW
): TimelineState['items'] {
  return items.slice(start, start + Math.min(size, TIMELINE_WINDOW))
}
