import { createElement, type ReactElement } from 'react'

export function FollowupList(props: {
  items: readonly string[]
  onPick: (task: string) => void
}): ReactElement {
  return createElement(
    'ul',
    { 'data-testid': 'followup-list', 'data-empty': props.items.length === 0 ? 'true' : 'false' },
    props.items.map((item) =>
      createElement(
        'li',
        { key: item },
        createElement('button', { type: 'button', onClick: () => props.onPick(item) }, item)
      )
    )
  )
}
