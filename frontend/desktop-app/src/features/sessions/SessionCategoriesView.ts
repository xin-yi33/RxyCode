import { createElement, type ReactElement } from 'react'
import { projectCategories, type CategorizedSession } from '../../lib/sessionCategories.ts'

export function SessionCategoriesView(props: {
  sessions: readonly CategorizedSession[]
  listDeletedAvailable: boolean
}): ReactElement {
  const buckets = projectCategories(props.sessions, props.listDeletedAvailable)
  return createElement(
    'div',
    { 'data-testid': 'session-categories', 'data-recycle-blocked': buckets.recycleBlocked ? 'true' : 'false' },
    createElement('section', { 'data-bucket': 'pinned' }, `${buckets.pinned.length}`),
    createElement('section', { 'data-bucket': 'projects' }, `${Object.keys(buckets.projects).length}`),
    createElement('section', { 'data-bucket': 'recent' }, `${buckets.recent.length}`)
  )
}
