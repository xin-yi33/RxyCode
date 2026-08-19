import { createElement, type ReactElement } from 'react'
import { contextWarn, usageRatio } from './statusline.config.ts'

export function UsageRing(props: { used: number; limit: number }): ReactElement {
  const ratio = usageRatio(props.used, props.limit)
  const warn = contextWarn(props.used, props.limit)
  return createElement('span', {
    className: 'usage-ring',
    'data-testid': 'usage-ring',
    'data-warn': warn ? 'true' : 'false',
    style: { ['--usage' as string]: String(ratio) },
    title: `${props.used}/${props.limit}`
  })
}
