import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
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
