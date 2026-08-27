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

test('GX23: schedule/* is path A', () => {
  const probe = probeSchedule(schema)
  assert.equal(probe.path, 'A')
  assert.ok(probe.present.includes('schedule/list'))
  const html = renderToStaticMarkup(
    createElement(SchedulePanel, { blocked: false, missing: [] })
  )
  assert.match(html, /data-testid="schedule-panel"/)
})
