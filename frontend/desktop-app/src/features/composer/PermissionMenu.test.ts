import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { PermissionMenu } from './PermissionMenu.ts'

const labels = {
  header: '应如何批准操作?',
  learnMore: '了解更多',
  confirmAll: '请求批准',
  confirmAllHint: '编辑外部文件和使用互联网时始终询问',
  autoEdit: '帮我批准',
  autoEditHint: '仅对检测到的风险操作请求批准',
  fullAuto: '完全访问',
  fullAutoHint: '不限制访问互联网和这台电脑上的文件',
  trigger: '权限'
}

test('PermissionMenu copies Codex rows: header, hints, hidden select testid', () => {
  const html = renderToStaticMarkup(
    createElement(PermissionMenu, {
      value: 'full_auto',
      onChange: () => undefined,
      labels
    })
  )
  assert.match(html, /data-testid="composer-permission-mode"/)
  assert.match(html, /<select/)
  assert.match(html, /permission-menu-trigger/)
  assert.match(html, /完全访问/)
  assert.match(html, /请求批准/)
  assert.match(html, /帮我批准/)
})

test('PermissionMenu marks only full_auto as warning and keeps the menu open after pick', () => {
  const autoEdit = renderToStaticMarkup(
    createElement(PermissionMenu, {
      value: 'auto_edit',
      onChange: () => undefined,
      labels
    })
  )
  const fullAuto = renderToStaticMarkup(
    createElement(PermissionMenu, {
      value: 'full_auto',
      onChange: () => undefined,
      labels
    })
  )
  const root = dirname(fileURLToPath(import.meta.url))
  const source = readFileSync(join(root, 'PermissionMenu.ts'), 'utf8')
  const css = readFileSync(join(root, '../../renderer/src/assets/main.css'), 'utf8')
  assert.match(autoEdit, /permission-menu-trigger[^>]*data-tone="default"/)
  assert.match(autoEdit, /permission-menu-trigger[^>]*data-mode="auto_edit"/)
  assert.match(fullAuto, /permission-menu-trigger[^>]*data-tone="warning"/)
  assert.match(source, /'data-tone': option\.value === 'full_auto' \? 'warning' : 'default'/)
  assert.match(source, /onClick: \(\) => \{\s*props\.onChange\(option\.value\)\s*\}/)
  assert.doesNotMatch(source, /props\.onChange\(option\.value\)\s*setOpen\(false\)/)
  assert.match(css, /\.permission-menu-trigger\s*\{[\s\S]*?border-radius:\s*8px/)
  assert.doesNotMatch(css, /\.permission-menu-trigger\s*\{[\s\S]*?border-radius:\s*999px/)
  assert.match(css, /\.permission-menu-option\.is-active[^{]*\{[^}]*background:\s*var\(--cc-surface-raised\)/)
  assert.match(css, /\.permission-menu-panel\s*\{[^}]*background:\s*var\(--cc-surface-raised\)/)
  assert.doesNotMatch(css, /\.permission-menu-panel\s*\{[^}]*background:\s*#2a2a2a/)
  assert.match(css, /\.permission-menu-option:hover[^{]*\{[^}]*background:\s*var\(--cc-surface-raised\)/)
  assert.doesNotMatch(css, /\.permission-menu-option\.is-active[^{]*\{[^}]*background:\s*#2a2a2a/)
  assert.match(css, /\.permission-menu-option\[data-tone='warning'\] strong/)
  assert.match(fullAuto, /permission-full-mark/)
  assert.doesNotMatch(autoEdit, /permission-full-mark/)
})

