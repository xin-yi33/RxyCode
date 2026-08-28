import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { colors } from '../../ui/tokens.ts'
import { workbenchTokens } from './workbenchLayout.ts'

const root = join(dirname(fileURLToPath(import.meta.url)), '../../..')
const css = readFileSync(join(root, 'src/renderer/src/assets/main.css'), 'utf8')

test('Codex 26.825 dark tokens are the shipped :root canvas', () => {
  assert.equal(workbenchTokens.canvas, '#0d0d0d')
  assert.equal(workbenchTokens.surface, '#000000')
  assert.equal(workbenchTokens.surfaceRaised, '#181818')
  assert.equal(workbenchTokens.hover, '#ffffff14')
  assert.equal(workbenchTokens.border, '#ffffff14')
  assert.equal(workbenchTokens.muted, '#ffffffa6')
  assert.equal(workbenchTokens.focus, '#339cffb3')
  assert.equal(colors.canvasDark, '#0d0d0d')
  assert.match(css, /--cc-canvas:\s*#0d0d0d/)
  assert.match(css, /--cc-surface:\s*#000000/)
  assert.match(css, /--cc-surface-raised:\s*#181818/)
  assert.match(css, /--cc-border:\s*#ffffff14/)
  assert.match(css, /--cc-muted:\s*#ffffffa6/)
  assert.match(css, /--cc-focus:\s*#339cffb3/)
  assert.doesNotMatch(css, /--cc-canvas:\s*#090a0c/)
  assert.doesNotMatch(css, /--cc-canvas:\s*#111318/)
})
