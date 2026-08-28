import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { colors } from '../../ui/tokens.ts'
import { sessionRailSelector, workbenchLayoutClass, workbenchTokens } from './workbenchLayout.ts'

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

test('desktop CSS shows a 248px left rail and does not globally hide it', () => {
  assert.equal(
    workbenchLayoutClass({ inspectorOpen: false, runPanelOpen: false, navOpen: false }),
    'main-layout command-layout'
  )
  assert.equal(
    workbenchLayoutClass({ inspectorOpen: false, runPanelOpen: true, navOpen: false }),
    'main-layout command-layout run-panel-open'
  )
  assert.equal(sessionRailSelector('block'), '.desktop-navigation-panel')
  assert.equal(sessionRailSelector('none'), '.nav-sheet')
  const override = css.split('RxyCode desktop command surface')[1] ?? ''
  const desktopDefault = override.split('@media')[0]
  assert.match(desktopDefault, /\.command-layout \{[\s\S]*?grid-template-columns:\s*248px\s+minmax\(0,\s*1fr\);/)
  assert.doesNotMatch(desktopDefault, /\.desktop-navigation-panel\s*\{[^}]*display:\s*none/)
  assert.match(desktopDefault, /\.desktop-navigation-panel\s*\{[^}]*display:\s*block/)
  assert.match(desktopDefault, /\.nav-toggle\s*\{[\s\S]*?display:\s*none/)
  assert.match(css, /@media \(max-width:\s*1279px\)[\s\S]*\.desktop-navigation-panel\s*\{[\s\S]*?display:\s*none/)
})

test('App ships a persistent desktop-navigation-panel SessionList', () => {
  const app = readFileSync(join(root, 'src/renderer/src/App.tsx'), 'utf8')
  assert.match(app, /className="desktop-navigation-panel"/)
  assert.match(app, /data-testid="workbench-layout"/)
  assert.match(app, /workbenchLayoutClass/)
  assert.doesNotMatch(app, /PermissionModeSwitcher/)
})

test('App mounts Statusline, PromptSuggestions, and review scope', () => {
  const app = readFileSync(join(root, 'src/renderer/src/App.tsx'), 'utf8')
  const inspector = readFileSync(join(root, 'src/renderer/src/components/TaskInspector.tsx'), 'utf8')
  assert.match(app, /Statusline/)
  assert.match(app, /PromptSuggestions/)
  assert.match(inspector, /ReviewScopeSelector/)
  assert.match(inspector, /review-diff-empty|ReviewScopeSelector/)
})
