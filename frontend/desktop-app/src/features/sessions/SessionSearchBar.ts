import { createElement, type ReactElement } from 'react'

export function SessionSearchBar(props: {
  query: string
  onChange: (value: string) => void
}): ReactElement {
  return createElement('input', {
    'data-testid': 'session-search',
    'aria-label': 'Search sessions',
    placeholder: 'Cmd+G',
    value: props.query,
    onChange: (event: React.ChangeEvent<HTMLInputElement>) => props.onChange(event.target.value)
  })
}
