import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { CHEVRON_GAP_PX, chevron, HOVER_DARK, HOVER_LIGHT, projectCategories } from '../../../lib/sessionCategories.ts'
import { sessionVisualState } from './sessionVisualState.ts'

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../assets/main.css'), 'utf8')

test('H15 five-state mapping covers empty/loading/error/narrow/dark', () => {
  assert.equal(sessionVisualState({ loading: true, error: null, empty: true, narrow: false, dark: true }), 'loading')
  assert.equal(sessionVisualState({ loading: false, error: 'x', empty: false, narrow: false, dark: true }), 'error')
  assert.equal(sessionVisualState({ loading: false, error: null, empty: true, narrow: false, dark: true }), 'empty')
  assert.equal(sessionVisualState({ loading: false, error: null, empty: false, narrow: true, dark: true }), 'narrow')
  assert.equal(sessionVisualState({ loading: false, error: null, empty: false, narrow: false, dark: true }), 'dark')
  assert.equal(sessionVisualState({ loading: false, error: null, empty: false, narrow: false, dark: false }), 'ok')
})

test('sidebar pins settings, adds project folders, and uses a dark theme menu', () => {
  const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'SessionList.tsx'), 'utf8')
  const composer = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'Composer.tsx'), 'utf8')
  const chat = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'ChatArea.tsx'), 'utf8')
  assert.match(src, /data-testid="add-project"/)
  assert.match(src, /data-testid="new-in-recent"/)
  assert.match(src, /data-testid=\{`new-in-project-\$\{/)
  assert.match(src, /session-scroll/)
  assert.match(src, /onAddProject/)
  assert.match(src, /onCreateInProject/)
  assert.doesNotMatch(src, /className="session-id"/)
  assert.doesNotMatch(src, /data-testid="session-recycle"/)
  assert.match(src, /data-testid=\{`pin-task-\$\{/)
  assert.match(src, /onPin/)
  assert.match(src, /session-actions/)
  assert.match(src, /session-unread-dot/)
  assert.match(src, /session-project-folder/)
  assert.match(src, /session-list-in-project/)
  assert.match(src, /TitleMarquee/)
  assert.match(src, /data-testid="sidebar-scheduled"/)
  assert.match(src, /data-testid="sidebar-plugins"/)
  assert.match(css, /\.archived-chats/)
  assert.match(css, /\.pin-button\.is-pinned/)
  assert.match(css, /\.session-row:hover \.session-actions/)
  assert.match(css, /\.session-item\.active\s*\{[\s\S]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.1/)
  assert.match(css, /\.status-indicator\[data-status='spin'\][\s\S]*#d0d7de|#8b949e|rgba\(255,\s*255,\s*255/)
  assert.match(css, /\.session-list-in-project \.session-row\s*\{[\s\S]*padding-left:\s*30px/)
  assert.match(css, /\.session-list-in-project \.session-item\s*\{[\s\S]*padding-left:\s*0/)
  assert.match(css, /@keyframes title-marquee-scroll/)
  assert.match(composer, /ThemeMenu/)
  assert.match(composer, /PermissionMenu/)
  assert.match(composer, /testId="composer-permission-mode"/)
  assert.match(composer, /testId="composer-model"/)
  assert.match(chat, /emptyChatGreeting/)
  assert.match(css, /\.session-scroll\s*\{/)
  assert.match(css, /\.theme-menu-panel\s*\{/)
  assert.match(css, /\.settings-page\s*\{[\s\S]*width:\s*1040px/)
  assert.match(css, /\.settings-page\s*\{[\s\S]*height:\s*720px/)
})

test('H15 three categories, chevron, recycle BLOCKED, hover sample in CSS', () => {
  const buckets = projectCategories(
    [
      { sessionId: 'p', title: 'a', workspaceRoot: '', pinned: true },
      { sessionId: 'proj', title: 'b', workspaceRoot: 'D:\\work', projectId: 'D:\\work' },
      { sessionId: 'r', title: 'c', workspaceRoot: '' }
    ],
    false
  )
  assert.equal(buckets.pinned[0]?.sessionId, 'p')
  assert.equal(buckets.projects['D:\\work']?.[0]?.sessionId, 'proj')
  assert.equal(buckets.recent[0]?.sessionId, 'r')
  assert.equal(buckets.recycleBlocked, true)
  assert.equal(chevron(true), 'v')
  assert.equal(chevron(false), '>')
  assert.equal(CHEVRON_GAP_PX, 4)
  assert.equal(HOVER_LIGHT, 'rgba(0,0,0,0.06)')
  assert.equal(HOVER_DARK, 'rgba(255,255,255,0.08)')
  assert.match(css, /rgba\(255,\s*255,\s*255,\s*0\.08\)/)
  assert.match(css, /rgba\(0,\s*0,\s*0,\s*0\.06\)/)
  assert.match(css, /margin-left:\s*4px/)
  assert.match(css, /session-panel\[data-visual-state='narrow'\]/)
})
