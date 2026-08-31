import { createElement, useLayoutEffect, useRef, useState, type ReactElement } from 'react'

export function TitleMarquee(props: { text: string; className?: string; testId?: string }): ReactElement {
  const wrapRef = useRef<HTMLSpanElement | null>(null)
  const trackRef = useRef<HTMLSpanElement | null>(null)
  const [overflow, setOverflow] = useState(false)

  useLayoutEffect(() => {
    const wrap = wrapRef.current
    const track = trackRef.current
    if (wrap === null || track === null) return
    const first = track.firstElementChild as HTMLElement | null
    const width = first?.scrollWidth ?? track.scrollWidth
    setOverflow(width > wrap.clientWidth + 1)
  }, [props.text])

  return createElement(
    'span',
    {
      ref: wrapRef,
      className: 'title-marquee' + (overflow ? ' is-overflow' : '') + (props.className !== undefined ? ` ${props.className}` : ''),
      'data-testid': props.testId,
      title: props.text
    },
    createElement(
      'span',
      { ref: trackRef, className: 'title-marquee-track' },
      createElement('span', { className: 'title-marquee-item' }, props.text),
      overflow ? createElement('span', { className: 'title-marquee-item', 'aria-hidden': true }, props.text) : null
    )
  )
}
