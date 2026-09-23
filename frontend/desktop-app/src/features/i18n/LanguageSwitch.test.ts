import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { isChatTextLocalized } from '../../i18n/t.ts'
import { gx22CatalogComplete } from './gx22.catalog.ts'
import { LanguageSwitch } from './LanguageSwitch.ts'

test('GX22: reuse H14 catalog; chat text not rewritten', () => {
  assert.equal(gx22CatalogComplete(), true)
  assert.equal(isChatTextLocalized('en', '你好世界'), '你好世界')
  const html = renderToStaticMarkup(
    createElement(LanguageSwitch, { locale: 'zh-CN', onChange: () => undefined })
  )
  assert.match(html, /data-testid="language-switch"/)
})
