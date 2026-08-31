import { Bot, Check, ChevronDown, Hand, Shield } from 'lucide-react'
import { createElement, useEffect, useRef, useState, type ReactElement } from 'react'

export type PermissionMenuMode = 'confirm_all' | 'auto_edit' | 'full_auto'

const OPTIONS: Array<{
  value: PermissionMenuMode
  icon: 'hand' | 'bot' | 'shield'
}> = [
  { value: 'confirm_all', icon: 'hand' },
  { value: 'auto_edit', icon: 'bot' },
  { value: 'full_auto', icon: 'shield' }
]

function ModeIcon(props: { name: 'hand' | 'bot' | 'shield' }): ReactElement {
  if (props.name === 'hand') return createElement(Hand, { size: 16, 'aria-hidden': true })
  if (props.name === 'bot') return createElement(Bot, { size: 16, 'aria-hidden': true })
  return createElement(Shield, { size: 16, 'aria-hidden': true })
}

export function PermissionMenu(props: {
  value: PermissionMenuMode
  onChange: (value: PermissionMenuMode) => void
  disabled?: boolean
  testId?: string
  labels: {
    header: string
    learnMore: string
    confirmAll: string
    confirmAllHint: string
    autoEdit: string
    autoEditHint: string
    fullAuto: string
    fullAutoHint: string
    trigger: string
  }
}): ReactElement {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const titles: Record<PermissionMenuMode, string> = {
    confirm_all: props.labels.confirmAll,
    auto_edit: props.labels.autoEdit,
    full_auto: props.labels.fullAuto
  }
  const hints: Record<PermissionMenuMode, string> = {
    confirm_all: props.labels.confirmAllHint,
    auto_edit: props.labels.autoEditHint,
    full_auto: props.labels.fullAutoHint
  }

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

  return createElement(
    'div',
    { className: 'permission-menu', ref: rootRef, 'data-testid': 'permission-menu' },
    createElement(
      'select',
      {
        className: 'theme-menu-native',
        'data-testid': props.testId ?? 'composer-permission-mode',
        'aria-hidden': true,
        tabIndex: -1,
        value: props.value,
        disabled: props.disabled === true,
        onChange: (event: { target: { value: string } }) =>
          props.onChange(event.target.value as PermissionMenuMode)
      },
      OPTIONS.map((option) =>
        createElement('option', { key: option.value, value: option.value }, titles[option.value])
      )
    ),
    createElement(
      'button',
      {
        type: 'button',
        className: 'permission-menu-trigger',
        'data-tone': props.value === 'full_auto' ? 'warning' : 'default',
        'aria-label': props.labels.trigger,
        'aria-expanded': open,
        disabled: props.disabled === true,
        onClick: () => setOpen((current) => !current)
      },
      createElement(Shield, { size: 14, 'aria-hidden': true }),
      titles[props.value],
      createElement(ChevronDown, { size: 13, 'aria-hidden': true })
    ),
    open
      ? createElement(
          'div',
          { className: 'permission-menu-panel', role: 'listbox' },
          createElement(
            'header',
            { className: 'permission-menu-head' },
            createElement('span', null, props.labels.header),
            createElement('span', { className: 'permission-menu-learn' }, props.labels.learnMore)
          ),
          OPTIONS.map((option) =>
            createElement(
              'button',
              {
                key: option.value,
                type: 'button',
                role: 'option',
                className:
                  'permission-menu-option' + (option.value === props.value ? ' is-active' : ''),
                'aria-selected': option.value === props.value,
                'data-testid': `permission-option-${option.value}`,
                onClick: () => {
                  props.onChange(option.value)
                  setOpen(false)
                }
              },
              createElement('span', { className: 'permission-menu-icon' }, createElement(ModeIcon, { name: option.icon })),
              createElement(
                'span',
                { className: 'permission-menu-copy' },
                createElement('strong', null, titles[option.value]),
                createElement('small', null, hints[option.value])
              ),
              option.value === props.value
                ? createElement(Check, { className: 'permission-menu-check', size: 16, 'aria-hidden': true })
                : null
            )
          )
        )
      : null
  )
}
