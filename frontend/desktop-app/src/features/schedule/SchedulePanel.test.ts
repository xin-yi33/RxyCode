import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { SchedulePanel } from './SchedulePanel.ts'
import { probeSchedule } from './schedule.probe.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX23: schedule/* missing', () => {
  const probe = probeSchedule(schema)
  assert.equal(probe.path, 'B')
  const html = renderToStaticMarkup(
    createElement(SchedulePanel, { blocked: true, missing: probe.missing })
  )
  assert.match(html, /schedule\/list/)
})
