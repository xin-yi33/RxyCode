import assert from 'node:assert/strict'
import { test } from 'node:test'
import { webPreferencesSafe } from './web-preferences.ts'

test('H3: BrowserWindow cannot disable isolation/sandbox', () => {
  const prefs = webPreferencesSafe({
    contextIsolation: false,
    nodeIntegration: true,
    sandbox: false,
    preload: 'preload.js'
  })
  assert.equal(prefs.contextIsolation, true)
  assert.equal(prefs.nodeIntegration, false)
  assert.equal(prefs.sandbox, true)
  assert.equal(prefs.preload, 'preload.js')
})
