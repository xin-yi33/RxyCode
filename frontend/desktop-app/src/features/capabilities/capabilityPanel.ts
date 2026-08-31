import { createElement, type ReactElement } from 'react'
import { isDeclaredCapability } from '@rxycode/protocol-client'
import type { CapabilityRow } from './capability.model.ts'

export function capabilityState(
  capabilities: Record<string, unknown> | null,
  name: string
): 'available' | 'degraded' {
  return isDeclaredCapability(capabilities, name) ? 'available' : 'degraded'
}

export function CapabilityPanel(props: {
  kind: 'skill' | 'mcp'
  items: readonly CapabilityRow[]
  loading?: boolean
  error?: string | null
  labels?: {
    empty?: string
    enabled?: string
    installed?: string
    available?: string
    connection?: string
  }
  onSetEnabled: (capabilityId: string, enabled: boolean) => void
}): ReactElement {
  const labels = {
    empty: props.labels?.empty ?? '暂无条目',
    enabled: props.labels?.enabled ?? '启用',
    installed: props.labels?.installed ?? '已安装',
    available: props.labels?.available ?? '可用',
    connection: props.labels?.connection ?? '连接'
  }
  return createElement(
    'div',
    { className: 'capability-list', 'data-testid': `capability-list-${props.kind}` },
    props.loading === true ? createElement('p', { 'data-testid': 'capability-loading' }, '…') : null,
    props.error != null && props.error !== ''
      ? createElement('p', { role: 'alert', 'data-testid': 'capability-error' }, props.error)
      : null,
    props.items.length === 0 && !props.loading && (props.error == null || props.error === '')
      ? createElement('p', { 'data-testid': 'capability-empty' }, labels.empty)
      : null,
    createElement(
      'ul',
      { className: 'capability-rows' },
      ...props.items.map((row) =>
        createElement(
          'li',
          {
            key: row.capabilityId,
            className: 'capability-row',
            'data-testid': `capability-row-${row.capabilityId}`
          },
          createElement('div', { className: 'capability-row-main' },
            createElement('strong', null, row.name),
            createElement(
              'span',
              { className: 'capability-meta' },
              [
                row.installed ? labels.installed : null,
                row.available ? labels.available : null,
                row.connection !== '' && row.connection !== 'n/a' ? `${labels.connection}: ${row.connection}` : null
              ]
                .filter((item): item is string => item != null)
                .join(' · ')
            ),
            row.error != null ? createElement('span', { className: 'capability-error' }, row.error) : null
          ),
          createElement(
            'label',
            { className: 'settings-toggle' },
            createElement('input', {
              type: 'checkbox',
              'data-testid': `capability-enabled-${row.capabilityId}`,
              checked: row.enabled,
              onChange: (event: { target: { checked: boolean } }) =>
                props.onSetEnabled(row.capabilityId, event.target.checked)
            }),
            labels.enabled
          )
        )
      )
    )
  )
}
