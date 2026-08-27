import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { SETTINGS_SECTIONS } from '../../lib/settingsSections.ts'
import { SettingsShell } from './SettingsShell.ts'

test('GX26: reuse H19 eight settings sections; no second settings truth', () => {
  assert.equal(SETTINGS_SECTIONS.length, 8)
  const html = renderToStaticMarkup(createElement(SettingsShell))
  assert.match(html, /data-section="models"/)
  assert.match(html, /data-section="recycle"/)
})
