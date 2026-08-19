import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { SessionCategoriesView } from './SessionCategoriesView.ts'

test('GX20: reuse H15 projectCategories three buckets', () => {
  const html = renderToStaticMarkup(
    createElement(SessionCategoriesView, {
      listDeletedAvailable: false,
      sessions: [
        { sessionId: '1', title: 'p', workspaceRoot: 'w', pinned: true },
        { sessionId: '2', title: 'r', workspaceRoot: '' }
      ]
    })
  )
  assert.match(html, /data-bucket="pinned"/)
  assert.match(html, /data-recycle-blocked="true"/)
})
