import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { PluginMarket } from './PluginMarket.ts'
import { probePlugins } from './plugin.probe.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX24: plugin/* missing', () => {
  const probe = probePlugins(schema)
  assert.equal(probe.path, 'B')
  const html = renderToStaticMarkup(
    createElement(PluginMarket, { blocked: true, missing: probe.missing })
  )
  assert.match(html, /plugin\/list/)
})
