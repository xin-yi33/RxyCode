import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { TitleMarquee } from './TitleMarquee.ts'
import {
  MARQUEE_PX_PER_SEC,
  marqueeDurationSec,
  marqueeOverflowPx,
  sharedMarqueePxPerSec
} from './titleMarqueeMath.ts'

test('TitleMarquee renders the first-sentence title without a looping clone', () => {
  const html = renderToStaticMarkup(createElement(TitleMarquee, { text: '没什么，只是打个招呼', className: 'session-title' }))
  assert.match(html, /title-marquee/)
  assert.match(html, /没什么，只是打个招呼/)
  assert.match(html, /session-title/)
  assert.match(html, /data-overflow="false"/)
})

test('overflow is zero when the title fits', () => {
  assert.equal(marqueeOverflowPx(120, 200), 0)
  assert.equal(marqueeDurationSec(0), 0)
})

test('longer titles take more time at the same pixel speed', () => {
  const short = marqueeDurationSec(64, 32)
  const long = marqueeDurationSec(320, 32)
  assert.equal(short, 2)
  assert.equal(long, 10)
  assert.ok(long > short)
})

test('shared speed follows the slowest overflowing title', () => {
  assert.equal(sharedMarqueePxPerSec([40, 80, 320]), MARQUEE_PX_PER_SEC)
  assert.equal(sharedMarqueePxPerSec([19]), MARQUEE_PX_PER_SEC)
  assert.equal(sharedMarqueePxPerSec([]), MARQUEE_PX_PER_SEC)
})
