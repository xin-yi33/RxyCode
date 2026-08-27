import { createElement, type ReactElement } from 'react'
import { TrashSection } from '../settings/TrashSection.ts'
import type { TrashItemModel } from '../../components/TrashItem.ts'

export { probeRecycle } from './recycle.probe.ts'

export function RecycleBin(props: {
  items: readonly TrashItemModel[]
  blocked: boolean
  missing: readonly string[]
  onRestore: (id: string) => void
  onPurgeConfirmed: () => void
}): ReactElement {
  return createElement(TrashSection, {
    items: props.items,
    blocked: props.blocked,
    missing: props.missing,
    onRestore: props.onRestore,
    onPurgeConfirmed: props.onPurgeConfirmed
  })
}
