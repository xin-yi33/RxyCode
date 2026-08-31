import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { ThemeMenu } from './ThemeMenu.ts'

test('ThemeMenu keeps a hidden native select for existing tests and a dark panel', () => {
  const html = renderToStaticMarkup(
    createElement(ThemeMenu, {
      value: 'full_auto',
      options: [
        { value: 'confirm_all', label: '更改前询问' },
        { value: 'full_auto', label: '完全访问' }
      ],
      onChange: () => undefined,
      testId: 'composer-permission-mode',
      ariaLabel: '权限',
      tone: 'warning',
      placement: 'up'
    })
  )
  assert.match(html, /data-testid="composer-permission-mode"/)
  assert.match(html, /<select/)
  assert.match(html, /option value="full_auto"/)
  assert.match(html, /theme-menu-trigger/)
  assert.match(html, /data-tone="warning"/)
  assert.match(html, /完全访问/)
})
