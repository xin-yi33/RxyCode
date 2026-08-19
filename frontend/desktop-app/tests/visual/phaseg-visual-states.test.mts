import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { sessionVisualState } from '../../src/renderer/src/components/sessionVisualState.ts'
import { statusVisualState } from '../../src/lib/statusProjection.ts'
import { galleryVisualState } from '../../src/features/preview/galleryVisualState.ts'
import { HOVER_DARK, HOVER_LIGHT } from '../../src/lib/sessionCategories.ts'
import { themes } from '../../src/ui/tokens.ts'
import { colors } from '../../src/ui/tokens.ts'

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../src/renderer/src/assets/main.css'),
  'utf8'
)

test('Grok visual: empty/loading/error/narrow/dark map to component states', () => {
  assert.equal(sessionVisualState({ loading: true, error: null, empty: false, narrow: false, dark: true }), 'loading')
  assert.equal(sessionVisualState({ loading: false, error: 'e', empty: false, narrow: false, dark: true }), 'error')
  assert.equal(sessionVisualState({ loading: false, error: null, empty: true, narrow: false, dark: true }), 'empty')
  assert.equal(sessionVisualState({ loading: false, error: null, empty: false, narrow: true, dark: true }), 'narrow')
  assert.equal(sessionVisualState({ loading: false, error: null, empty: false, narrow: false, dark: true }), 'dark')
  assert.equal(statusVisualState({ empty: true, loading: false, error: false, narrow: false, dark: true }), 'empty')
  assert.equal(
    galleryVisualState({ artifacts: [], loading: false, error: 'x', narrow: false, dark: true }),
    'error'
  )
})

test('Grok visual: hover, high-contrast, risk not color-only, status animation, settings entry', () => {
  assert.equal(HOVER_LIGHT, 'rgba(0,0,0,0.06)')
  assert.equal(HOVER_DARK, 'rgba(255,255,255,0.08)')
  assert.ok(themes.includes('high-contrast'))
  assert.ok(colors.risk.text.length > 0)
  assert.ok(colors.risk.icon.length > 0)
  assert.match(css, /@keyframes status-spin/)
  assert.match(css, /\.status-indicator\[data-status='error'\]/)
  assert.match(css, /\.status-indicator\[data-status='dot'\]/)
  assert.match(css, /\.settings-entry \{/)
  assert.match(css, /border-radius:\s*6px/)
  assert.match(css, /session-panel\[data-visual-state='narrow'\]/)
  assert.match(css, /\.composer \{[\s\S]*?z-index:\s*\d+/)
})

test('Grok visual: approval overlay and settings dialog remain layered above canvas', () => {
  assert.match(css, /\.approval-overlay|\.settings-overlay/)
  assert.match(css, /\.settings-page/)
})
