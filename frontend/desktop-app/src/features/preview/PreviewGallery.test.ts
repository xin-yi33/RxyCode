import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { PreviewGallery } from './previewGallery.ts'
import { artifactView, canRender, toFileUrl } from './previewArtifacts.ts'

test('H19: PreviewGallery renders img/video/pre for hero/gallery/video/json', () => {
  const html = renderToStaticMarkup(
    createElement(PreviewGallery, {
      artifacts: [
        { kind: 'hero', path: 'D:\\proj\\.cli-anything\\previews\\hero.png', bytes: 100 },
        { kind: 'gallery', path: '/tmp/g.png', bytes: 10 },
        { kind: 'video', path: '/tmp/v.mp4', bytes: 10, durationSec: 4 },
        {
          kind: 'json',
          path: '/tmp/summary.json',
          bytes: 10,
          summary: { headline: 'done', facts: ['a'], warnings: [], next_actions: ['next'] }
        }
      ]
    })
  )
  assert.match(html, /data-kind="hero"/)
  assert.match(html, /<img/)
  assert.match(html, /max-width:1280px/)
  assert.match(html, /data-kind="gallery"/)
  assert.match(html, /<video/)
  assert.match(html, /data-kind="video"/)
  assert.match(html, /<pre/)
  assert.match(html, /data-kind="json"/)
  assert.match(html, /done/)
  assert.equal(canRender({ kind: 'video', path: 'x', bytes: 1, durationSec: 9 }), false)
  assert.equal(canRender({ kind: 'hero', path: 'x', bytes: 25 * 1024 * 1024 + 1 }), false)
  assert.equal(toFileUrl('D:\\a\\b.png'), 'file:///D:/a/b.png')
  assert.equal(artifactView({ kind: 'hero', path: '/a.png', bytes: 1 }).tag, 'img')
  assert.equal(artifactView({ kind: 'hero', path: '/a.png', bytes: 1 }).maxWidth, 1280)
})
