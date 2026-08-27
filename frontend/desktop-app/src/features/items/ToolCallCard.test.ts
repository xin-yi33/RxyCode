import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { shouldAutoFold, todoState, type ToolItem } from './autoFold.ts'
import { TodoTimeline } from './TodoTimeline.ts'
import { ToolCallCard } from './ToolCallCard.ts'

const base: ToolItem = { id: 't1', tool: 'read_file', status: 'success' }

test('GX6: auto-fold only success without diff; errors stay open', () => {
  assert.equal(shouldAutoFold({ ...base, status: 'success' }, true), true)
  assert.equal(shouldAutoFold({ ...base, status: 'success', referencesDiff: true }, true), false)
  assert.equal(shouldAutoFold({ ...base, status: 'failed' }, true), false)
  assert.equal(shouldAutoFold({ ...base, status: 'timeout' }, true), false)
  assert.equal(shouldAutoFold({ ...base, status: 'waiting_approval' }, true), false)
  assert.equal(shouldAutoFold({ ...base, status: 'success' }, false), false)
})

test('GX6: six badges, todo states, five-state markup', () => {
  assert.equal(todoState('pending'), 'empty')
  assert.equal(todoState('running'), 'spin')
  assert.equal(todoState('done'), 'check')
  const html = renderToStaticMarkup(
    createElement(ToolCallCard, { item: { ...base, status: 'failed', durationMs: 12 }, foldEnabled: true })
  )
  assert.match(html, /data-status="failed"/)
  assert.match(html, /data-folded="false"/)
  const todo = renderToStaticMarkup(
    createElement(TodoTimeline, {
      steps: [
        { id: '1', title: 'plan', status: 'done' },
        { id: '2', title: 'edit', status: 'running' }
      ]
    })
  )
  assert.match(todo, /data-todo="check"/)
  assert.match(todo, /data-todo="spin"/)
})
