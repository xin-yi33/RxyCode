import { createElement, type ReactElement } from 'react'
import { UsageRing } from './UsageRing.ts'
import {
  DEFAULT_STATUSLINE,
  gx7VisualState,
  visibleStatuslineItems,
  type StatuslineItemId
} from './statusline.config.ts'
import { probeMethods } from '../../features/gx/schemaProbe.ts'

export function statuslineUsageSource(schemaText: string): {
  event: 'event/token_usage' | null
  agentUsage: boolean
  pendingPricing: boolean
} {
  const probe = probeMethods(schemaText, ['event/token_usage', 'event/agent_usage'])
  return {
    event: probe.present.includes('event/token_usage') ? 'event/token_usage' : null,
    agentUsage: probe.present.includes('event/agent_usage'),
    pendingPricing: true
  }
}

export function Statusline(props: {
  hasSession: boolean
  model?: string
  used?: number
  limit?: number
  tokens?: number
  gitBranch?: string
  progress?: string
  enabled?: readonly StatuslineItemId[]
  loading?: boolean
  error?: string | null
  narrow?: boolean
  dark?: boolean
}): ReactElement | null {
  const visual = gx7VisualState({
    hasSession: props.hasSession,
    loading: props.loading === true,
    error: props.error ?? null,
    narrow: props.narrow === true,
    dark: props.dark === true
  })
  if (visual === 'hidden') return null
  const items = visibleStatuslineItems(props.enabled ?? DEFAULT_STATUSLINE, {
    hasPricing: false,
    narrow: props.narrow === true
  })
  return createElement(
    'footer',
    {
      className: 'statusline',
      'data-testid': 'statusline',
      'data-visual-state': visual,
      'data-source': 'event/token_usage'
    },
    items.includes('model') ? createElement('span', { 'data-item': 'model' }, props.model ?? '') : null,
    items.includes('context')
      ? createElement(UsageRing, { used: props.used ?? 0, limit: props.limit ?? 0 })
      : null,
    items.includes('tokens') ? createElement('span', { 'data-item': 'tokens' }, String(props.tokens ?? 0)) : null,
    items.includes('git_branch')
      ? createElement('span', { 'data-item': 'git_branch' }, props.gitBranch ?? '')
      : null,
    items.includes('task_progress')
      ? createElement('span', { 'data-item': 'task_progress' }, props.progress ?? '')
      : null
  )
}
