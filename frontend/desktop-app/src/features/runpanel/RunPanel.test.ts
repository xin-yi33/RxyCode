import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { RunPanel, SummarySection } from './RunPanel.ts'

test('GX10: four sections; summary hidden when usage event absent', () => {
  const html = renderToStaticMarkup(
    createElement(RunPanel, {
      open: true,
      usageAvailable: false,
      model: { plan: 'do x', sources: [], files: ['a.ts'], running: true, tokensUsed: 9, step: 'edit' }
    })
  )
  assert.match(html, /data-section="plan"/)
  assert.match(html, /data-section="sources"/)
  assert.match(html, /data-section="files"/)
  assert.doesNotMatch(html, /data-section="summary"/)
  const withUsage = renderToStaticMarkup(
    createElement(SummarySection, { available: true, tokensUsed: 3, step: 's' })
  )
  assert.match(withUsage, /tokens=3/)
})

test('GX10: collapsed after run and not a modal', () => {
  const html = renderToStaticMarkup(
    createElement(RunPanel, {
      open: false,
      usageAvailable: true,
      model: { plan: '', sources: [], files: [], running: false }
    })
  )
  assert.match(html, /run-panel-collapsed/)
  assert.doesNotMatch(html, /aria-modal/)
})
