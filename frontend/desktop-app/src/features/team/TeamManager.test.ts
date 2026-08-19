import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { TeamManager, probeTeam } from './TeamManager.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX28: consume existing team/*; Desktop only, no opentui', () => {
  const probe = probeTeam(schema)
  assert.equal(probe.path, 'A')
  const html = renderToStaticMarkup(
    createElement(TeamManager, {
      groups: [{ id: 'g1', name: 'reviewers' }],
      onInstall: () => undefined,
      onActivate: () => undefined
    })
  )
  assert.match(html, /reviewers/)
  assert.match(html, /Set active/)
})
