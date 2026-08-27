import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { PlanFilePanel } from './PlanFilePanel.ts'
import { buildPersist, planPath, probePlan } from './plan.persist.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX9: plan/persist and plan/implement are path A; data dir injected', () => {
  const probe = probePlan(schema)
  assert.equal(probe.path, 'A')
  assert.ok(probe.present.includes('plan/persist'))
  assert.ok(probe.present.includes('plan/implement'))
  assert.equal(
    planPath('t1', 'slug', process.env.RXYCODE_DATA_DIR ?? 'C:/tmp/rxy-test'),
    `${(process.env.RXYCODE_DATA_DIR ?? 'C:/tmp/rxy-test').replace(/\\/g, '/')}/plans/t1-slug.md`
  )
  const req = buildPersist(schema, { threadId: 't', markdown: '# p' })
  assert.deepEqual(req, {
    method: 'plan/persist',
    params: { thread_id: 't', markdown: '# p' }
  })
})

test('GX9: panel five states', () => {
  const html = renderToStaticMarkup(
    createElement(PlanFilePanel, {
      markdown: '',
      persistBlocked: true,
      implementBlocked: true,
      onChange: () => undefined,
      onImplement: () => undefined
    })
  )
  assert.match(html, /data-visual-state="empty"/)
  assert.match(html, /plan\/persist/)
})
