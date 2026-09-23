import { ChevronDown } from 'lucide-react'
import { createElement, useEffect, useRef, useState, type ReactElement } from 'react'

export interface ThemeMenuOption {
  value: string
  label: string
  group?: string
  disabled?: boolean
}

export function ThemeMenu(props: {
  value: string
  options: readonly ThemeMenuOption[]
  onChange: (value: string) => void
  disabled?: boolean
  testId: string
  ariaLabel: string
  title?: string
  tone?: 'default' | 'warning'
  placement?: 'up' | 'down'
  align?: 'start' | 'end'
}): ReactElement {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const selected = props.options.find((option) => option.value === props.value)
  const groups = groupOptions(props.options)

  useEffect(() => {
    if (!open) return
    const onPointer = (event: MouseEvent): void => {
      if (rootRef.current !== null && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', onPointer)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onPointer)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  const nativeChildren = groups.map(([group, items]) => {
    const options = items.map((option) =>
      createElement(
        'option',
        { key: option.value, value: option.value, disabled: option.disabled === true },
        option.label
      )
    )
    return group === ''
      ? options
      : createElement('optgroup', { key: group, label: group }, options)
  })

  return createElement(
    'div',
    {
      className: 'theme-menu',
      'data-placement': props.placement ?? 'up',
      'data-align': props.align ?? 'start',
      ref: rootRef
    },
    createElement(
      'select',
      {
        className: 'theme-menu-native',
        'data-testid': props.testId,
        'aria-hidden': true,
        tabIndex: -1,
        value: props.value,
        disabled: props.disabled === true,
        onChange: (event: { target: { value: string } }) => props.onChange(event.target.value)
      },
      nativeChildren
    ),
    createElement(
      'button',
      {
        type: 'button',
        className: 'theme-menu-trigger',
        'data-tone': props.tone ?? 'default',
        'aria-label': props.ariaLabel,
        'aria-expanded': open,
        title: props.title ?? props.ariaLabel,
        disabled: props.disabled === true,
        onClick: () => setOpen((current) => !current)
      },
      selected?.label ?? props.value,
      createElement(ChevronDown, { 'aria-hidden': true, size: 13 })
    ),
    open
      ? createElement(
          'div',
          { className: 'theme-menu-panel', role: 'listbox' },
          groups.flatMap(([group, items]) => {
            const heading =
              group === ''
                ? []
                : [createElement('p', { key: `g-${group}`, className: 'theme-menu-group' }, group)]
            return [
              ...heading,
              ...items.map((option) =>
                createElement(
                  'button',
                  {
                    key: option.value,
                    type: 'button',
                    role: 'option',
                    className:
                      'theme-menu-option' +
                      (option.value === props.value ? ' is-active' : '') +
                      (option.disabled === true ? ' is-disabled' : ''),
                    'aria-selected': option.value === props.value,
                    disabled: option.disabled === true,
                    onClick: () => {
                      if (option.disabled === true) return
                      props.onChange(option.value)
                      setOpen(false)
                    }
                  },
                  option.label
                )
              )
            ]
          })
        )
      : null
  )
}

function groupOptions(options: readonly ThemeMenuOption[]): Array<[string, ThemeMenuOption[]]> {
  const grouped = new Map<string, ThemeMenuOption[]>()
  for (const option of options) {
    const key = option.group ?? ''
    const bucket = grouped.get(key) ?? []
    bucket.push(option)
    grouped.set(key, bucket)
  }
  return [...grouped.entries()]
}
