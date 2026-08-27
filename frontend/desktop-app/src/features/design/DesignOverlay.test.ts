import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { DesignOverlay } from './DesignOverlay.ts'
import { addPin, pinsToDraft } from './designMode.ts'

test('GX15: pins become a local draft; no protocol', () => {
  const pins = addPin([], { id: '1', x: 1, y: 2, note: 'move button' })
  assert.match(pinsToDraft(pins), /move button/)
  const html = renderToStaticMarkup(
    createElement(DesignOverlay, { active: true, pins, onPin: () => undefined })
  )
  assert.match(html, /data-testid="design-overlay"/)
})
