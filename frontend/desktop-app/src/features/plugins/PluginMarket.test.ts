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
  assert.match(html, /data-testid="plugin-hub-nav"/)
  assert.match(html, /data-testid="plugin-hub-plugins"/)
  assert.match(html, /data-testid="plugin-hub-skills"/)
  assert.match(html, /data-testid="plugin-hub-teams"/)
  assert.match(html, /data-testid="plugin-github"/)
  assert.match(html, /data-testid="plugin-hub-add"/)
  assert.match(html, /class="plugin-hub-add"/)
})

test('plugin hub uses a fixed right pane and square add controls', () => {
  const root = dirname(fileURLToPath(import.meta.url))
  const css = readFileSync(join(root, '../../renderer/src/assets/main.css'), 'utf8')
  const app = readFileSync(join(root, '../../renderer/src/App.tsx'), 'utf8')
  assert.match(app, /data-testid="plugin-hub-slot"/)
  assert.doesNotMatch(app, /rail-panel-wide/)
  assert.match(css, /\.plugin-hub-add\s*\{[\s\S]*?border-radius:\s*8px/)
  assert.match(css, /\.plugin-hub-add\s*\{[\s\S]*?background:\s*#fff/)
  assert.match(css, /\.skill-card-add\s*\{[\s\S]*?border-radius:\s*8px/)
  assert.doesNotMatch(css, /\.skill-card-add\s*\{[\s\S]*?border-radius:\s*50%/)
  assert.match(css, /\.skill-card-add\s*\{[\s\S]*?padding:\s*0/)
})
