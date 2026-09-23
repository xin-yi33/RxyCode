import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { FollowupList } from './FollowupList.ts'
import { scanFollowups } from './followup.scanner.ts'

test('GX18: rule scanner, zero LLM', () => {
  const items = scanFollowups([{ text: 'typecheck failed' }, { text: 'open the review' }])
  assert.ok(items.includes('Fix lint or typecheck errors'))
  const html = renderToStaticMarkup(
    createElement(FollowupList, { items, onPick: () => undefined })
  )
  assert.match(html, /data-testid="followup-list"/)
})
