import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { TitleMarquee } from './TitleMarquee.ts'

test('TitleMarquee renders the first-sentence title', () => {
  const html = renderToStaticMarkup(createElement(TitleMarquee, { text: '没什么，只是打个招呼', className: 'session-title' }))
  assert.match(html, /title-marquee/)
  assert.match(html, /没什么，只是打个招呼/)
  assert.match(html, /session-title/)
})
