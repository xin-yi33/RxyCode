import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { VersionCard } from './VersionCard.ts'
import { versionsFromTurns } from './version.timeline.ts'

test('GX17: each turn is a version; rewind disabled when GX4 protocol missing', () => {
  const cards = versionsFromTurns([{ turnId: 't1', summary: 'edit a.ts', fileCount: 1 }])
  assert.equal(cards[0]?.version, 1)
  const html = renderToStaticMarkup(
    createElement(VersionCard, {
      card: cards[0]!,
      rewindEnabled: false,
      onDiff: () => undefined,
      onRewind: () => undefined
    })
  )
  assert.match(html, /v1/)
  assert.match(html, /GX4 blocked/)
})
