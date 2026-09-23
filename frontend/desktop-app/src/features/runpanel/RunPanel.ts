import { createElement, type ReactElement } from 'react'

export interface RunPanelModel {
  plan: string
  sources: string[]
  files: string[]
  tokensUsed?: number
  step?: string
  running: boolean
}

export function gx10VisualState(input: {
  loading: boolean
  error: string | null
  empty: boolean
  narrow: boolean
  dark: boolean
}): 'loading' | 'error' | 'empty' | 'narrow' | 'dark' | 'ok' {
  if (input.loading) return 'loading'
  if (input.error !== null) return 'error'
  if (input.empty) return 'empty'
  if (input.narrow) return 'narrow'
  if (input.dark) return 'dark'
  return 'ok'
}

export function PlanSection(props: { plan: string }): ReactElement {
  return createElement('section', { 'data-section': 'plan' }, props.plan || 'No plan')
}

export function SourcesSection(props: { sources: readonly string[] }): ReactElement {
  return createElement(
    'section',
    { 'data-section': 'sources' },
    props.sources.length === 0 ? 'No sources field on this branch' : props.sources.join(', ')
  )
}

export function FilesSection(props: { files: readonly string[] }): ReactElement {
  return createElement(
    'section',
    { 'data-section': 'files' },
    props.files.length === 0 ? 'No file changes' : props.files.join(', ')
  )
}

export function SummarySection(props: { tokensUsed?: number; step?: string; available: boolean }): ReactElement | null {
  if (!props.available) return null
  return createElement(
    'section',
    { 'data-section': 'summary' },
    `tokens=${props.tokensUsed ?? 0} step=${props.step ?? ''}`
  )
}

export function RunPanel(props: {
  model: RunPanelModel
  open: boolean
  usageAvailable: boolean
  loading?: boolean
  error?: string | null
  narrow?: boolean
  dark?: boolean
}): ReactElement {
  const visual = gx10VisualState({
    loading: props.loading === true,
    error: props.error ?? null,
    empty: !props.open,
    narrow: props.narrow === true,
    dark: props.dark === true
  })
  if (!props.open && !props.model.running) {
    return createElement('div', { 'data-testid': 'run-panel-collapsed', 'data-visual-state': visual }, 'Run summary')
  }
  return createElement(
    'aside',
    {
      className: 'run-panel',
      'data-testid': 'run-panel',
      'data-visual-state': visual,
      'aria-label': 'agent run panel'
    },
    createElement(PlanSection, { plan: props.model.plan }),
    createElement(SourcesSection, { sources: props.model.sources }),
    createElement(FilesSection, { files: props.model.files }),
    props.model.running
      ? createElement(SummarySection, {
          tokensUsed: props.model.tokensUsed,
          step: props.model.step,
          available: props.usageAvailable
        })
      : null
  )
}
