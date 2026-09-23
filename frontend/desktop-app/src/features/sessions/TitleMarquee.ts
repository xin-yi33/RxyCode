import { createElement, useLayoutEffect, useRef, useState, type CSSProperties, type ReactElement } from 'react'
import { marqueeDurationSec, marqueeOverflowPx } from './titleMarqueeMath.ts'

export function TitleMarquee(props: {
  text: string
  className?: string
  testId?: string
  pxPerSec?: number
  onOverflow?: (overflowPx: number) => void
}): ReactElement {
  const wrapRef = useRef<HTMLSpanElement | null>(null)
  const itemRef = useRef<HTMLSpanElement | null>(null)
  const [overflow, setOverflow] = useState(0)

  useLayoutEffect(() => {
    const wrap = wrapRef.current
    const item = itemRef.current
    if (wrap === null || item === null) return
    const measure = (): void => {
      setOverflow(marqueeOverflowPx(item.scrollWidth, wrap.clientWidth))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(wrap)
    observer.observe(item)
    return () => observer.disconnect()
  }, [props.text])

  useLayoutEffect(() => {
    props.onOverflow?.(overflow)
  }, [overflow, props.onOverflow])

  const duration = marqueeDurationSec(overflow, props.pxPerSec)
  const style = {
    '--title-marquee-duration': `${duration}s`,
    '--title-marquee-distance': `${overflow}px`
  } as CSSProperties

  return createElement(
    'span',
    {
      ref: wrapRef,
      className:
        'title-marquee' +
        (overflow > 0 ? ' is-overflow' : '') +
        (props.className !== undefined ? ` ${props.className}` : ''),
      'data-testid': props.testId,
      'data-overflow': overflow > 0 ? 'true' : 'false',
      title: props.text,
      style
    },
    createElement(
      'span',
      { className: 'title-marquee-track' },
      createElement('span', { ref: itemRef, className: 'title-marquee-item' }, props.text)
    )
  )
}
