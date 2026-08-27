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

test('GX24: plugin/* is path A', () => {
  const probe = probePlugins(schema)
  assert.equal(probe.path, 'A')
  assert.ok(probe.present.includes('plugin/list'))
  const html = renderToStaticMarkup(
    createElement(PluginMarket, { blocked: false, missing: [] })
  )
  assert.match(html, /data-testid="plugin-market"/)
})
