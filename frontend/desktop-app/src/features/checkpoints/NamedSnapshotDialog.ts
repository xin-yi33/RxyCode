import { createElement, useState, type ReactElement } from 'react'

export function NamedSnapshotDialog(props: {
  blocked: boolean
  onCreate: (name: string) => void
}): ReactElement {
  const [name, setName] = useState('')
  return createElement(
    'form',
    {
      className: 'named-snapshot',
      'data-testid': 'named-snapshot',
      onSubmit: (event: React.FormEvent) => {
        event.preventDefault()
        if (!props.blocked) props.onCreate(name)
      }
    },
    createElement('input', {
      value: name,
      placeholder: 'Snapshot name',
      disabled: props.blocked,
      onChange: (event: React.ChangeEvent<HTMLInputElement>) => setName(event.target.value)
    }),
    createElement('button', { type: 'submit', disabled: props.blocked }, props.blocked ? 'BLOCKED' : 'Save snapshot')
  )
}
