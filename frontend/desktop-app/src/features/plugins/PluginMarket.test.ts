import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { GithubPopularRow, PluginMarket } from './PluginMarket.ts'
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
  assert.match(html, /data-testid="plugin-github-connect"/)
  assert.match(html, /data-testid="plugin-github-add"/)
  assert.match(html, /data-testid="plugin-canva"/)
  assert.match(html, /data-testid="plugin-canva-connect"/)
  assert.match(html, /data-testid="plugin-canva-add"/)
  assert.match(html, />连接</)
  assert.match(html, />添加</)
  assert.doesNotMatch(html, /GitHub Personal Access Token/)
  assert.doesNotMatch(html, /data-testid="plugin-github-token"/)
  assert.doesNotMatch(html, /mcpServers/)
  assert.match(html, /data-testid="plugin-hub-add"/)
  assert.match(html, /class="plugin-hub-add"/)
  const hook = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), '../../renderer/src/hooks/usePlugins.ts'),
    'utf8'
  )
  assert.match(hook, /plugin\/connect\/start/)
  assert.match(hook, /plugin\/catalog/)
})

test('plugin hub replaces the main session pane and keeps square add controls', () => {
  const root = dirname(fileURLToPath(import.meta.url))
  const css = readFileSync(join(root, '../../renderer/src/assets/main.css'), 'utf8')
  const app = readFileSync(join(root, '../../renderer/src/App.tsx'), 'utf8')
  assert.match(app, /data-testid="plugin-hub-slot"/)
  assert.match(app, /railPanel === 'plugins'[\s\S]*plugin-hub-slot/)
  assert.doesNotMatch(app, /<aside className="plugin-hub-slot"/)
  assert.doesNotMatch(app, /rail-panel-wide/)
  assert.match(css, /\.plugin-hub-add\s*\{[\s\S]*?border-radius:\s*8px/)
  assert.match(css, /\.plugin-hub-add\s*\{[\s\S]*?background:\s*#fff/)
  assert.match(css, /\.skill-card-add\s*\{[^}]*border-radius:\s*8px/)
  assert.doesNotMatch(css, /\.skill-card-add\s*\{[^}]*border-radius:\s*50%/)
  assert.match(css, /\.skill-card-add\s*\{[^}]*padding:\s*0/)
})

test('github popular row uses oauth connect not PAT', () => {
  const connect = renderToStaticMarkup(
    createElement(GithubPopularRow, {
      state: 'connect',
      onConnect: () => undefined
    })
  )
  assert.doesNotMatch(connect, /data-testid="plugin-github-token"/)
  assert.doesNotMatch(connect, /GitHub Personal Access Token/)
  assert.match(connect, /data-testid="plugin-github-connect"/)
  assert.match(connect, /data-testid="plugin-github-add"/)
  assert.match(connect, />连接</)
  assert.match(connect, />添加</)
  const connected = renderToStaticMarkup(
    createElement(GithubPopularRow, {
      state: 'connected',
      onConnect: () => undefined
    })
  )
  assert.match(connected, /data-testid="plugin-github-connected"/)
  assert.match(connected, /已连接/)
})
