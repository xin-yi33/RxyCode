import { createElement, useRef, type ReactElement } from 'react'
import { applySnapDrag, bandOf, type SashAxis, type SashBand, type SnapSpec } from './snapSash.ts'

export function WorkbenchSash(props: {
  axis: SashAxis
  spec: SnapSpec
  size: number
  testId: string
  className?: string
  invert?: boolean
  onSize: (size: number, snap: boolean) => void
  onCollapsed?: () => void
}): ReactElement {
  const dragRef = useRef<{
    origin: SashBand
    startPointer: number
    startSize: number
    dwellStartedAt: number | null
  } | null>(null)
  const propsRef = useRef(props)
  propsRef.current = props

  const stopDrag = (): void => {
    dragRef.current = null
    window.removeEventListener('pointermove', onWindowMove)
    window.removeEventListener('pointerup', onWindowUp)
    window.removeEventListener('pointercancel', onWindowUp)
  }

  const onWindowMove = (event: PointerEvent): void => {
    const drag = dragRef.current
    const current = propsRef.current
    if (drag === null) return
    const pointer = current.axis === 'vertical' ? event.clientX : event.clientY
    const delta = (pointer - drag.startPointer) * (current.invert === true ? -1 : 1)
    const next = applySnapDrag(current.spec, {
      origin: drag.origin,
      proposed: drag.startSize + delta,
      now: Date.now(),
      dwellStartedAt: drag.dwellStartedAt
    })
    drag.dwellStartedAt = next.dwellStartedAt
    current.onSize(next.size, next.snap)
    if (next.band === 'collapsed') current.onCollapsed?.()
  }

  const onWindowUp = (): void => {
    stopDrag()
  }

  const onPointerDown = (event: {
    clientX: number
    clientY: number
    pointerId: number
    currentTarget: HTMLElement
    preventDefault: () => void
  }): void => {
    event.preventDefault()
    try {
      event.currentTarget.setPointerCapture(event.pointerId)
    } catch {
      // Synthetic CDP events may not support capture; window listeners still work.
    }
    dragRef.current = {
      origin: bandOf(props.size, props.spec),
      startPointer: props.axis === 'vertical' ? event.clientX : event.clientY,
      startSize: props.size,
      dwellStartedAt: null
    }
    window.addEventListener('pointermove', onWindowMove)
    window.addEventListener('pointerup', onWindowUp)
    window.addEventListener('pointercancel', onWindowUp)
  }

  return createElement('div', {
    className: `workbench-sash workbench-sash-${props.axis}${props.className !== undefined ? ` ${props.className}` : ''}`,
    'data-testid': props.testId,
    role: 'separator',
    'aria-orientation': props.axis === 'vertical' ? 'vertical' : 'horizontal',
    'aria-valuenow': props.size,
    'aria-valuemin': 0,
    'aria-valuemax': props.spec.max,
    onPointerDown
  })
}
