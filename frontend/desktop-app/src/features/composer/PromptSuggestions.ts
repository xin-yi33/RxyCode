import { createElement, type ReactElement } from 'react'

export function PromptSuggestions(props: {
  items: readonly string[]
  visible: boolean
  onPick: (text: string) => void
}): ReactElement | null {
  if (!props.visible || props.items.length === 0) return null
  return createElement(
    'ul',
    { className: 'prompt-suggestions', 'data-testid': 'prompt-suggestions' },
    props.items.map((item) =>
      createElement(
        'li',
        { key: item },
        createElement('button', { type: 'button', onClick: () => props.onPick(item) }, item)
      )
    )
  )
}
