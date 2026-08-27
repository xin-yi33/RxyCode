import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { RunStatusVisual } from './RunStatusVisual.ts'

test('GX27: reuse H17 status projection spin/dot/error', () => {
  const running = renderToStaticMarkup(createElement(RunStatusVisual, { runState: 'running' }))
  assert.match(running, /data-visual="spin"/)
  const done = renderToStaticMarkup(createElement(RunStatusVisual, { runState: 'succeeded' }))
  assert.match(done, /data-visual="dot"/)
})
