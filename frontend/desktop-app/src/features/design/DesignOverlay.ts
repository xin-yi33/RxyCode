import { createElement, type ReactElement } from 'react'
import { gx15VisualState, type DesignPin } from './designMode.ts'

export function DesignOverlay(props: {
  active: boolean
  pins: readonly DesignPin[]
  dark?: boolean
  onPin: (x: number, y: number) => void
}): ReactElement {
  const visual = gx15VisualState({
    active: props.active,
    empty: props.pins.length === 0,
    error: null,
    narrow: false,
    dark: props.dark === true
  })
  return createElement(
    'div',
    {
      className: 'design-overlay',
      'data-testid': 'design-overlay',
      'data-visual-state': visual,
      onClick: (event: React.MouseEvent<HTMLDivElement>) => {
        if (!props.active) return
        props.onPin(event.clientX, event.clientY)
      }
    },
    props.pins.map((pin) =>
      createElement('span', { key: pin.id, className: 'design-pin', 'data-pin': pin.id }, pin.note)
    )
  )
}
