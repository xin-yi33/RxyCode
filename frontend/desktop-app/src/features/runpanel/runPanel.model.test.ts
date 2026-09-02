import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { RunPanel } from './RunPanel.ts'
import { projectRunPanel } from './runPanel.model.ts'

test('projectRunPanel maps plan/files/usage and opens while running', () => {
  const projected = projectRunPanel(
    {
      planBySession: { s1: ['edit composer', 'run tests'] },
      progressBySession: { s1: 'editing' },
      usageBySession: {
        s1: {
          inputTokens: 10,
          outputTokens: 5,
          reportingStatus: 'reported'
        }
      },
      timelineBySession: {
        s1: [
          {
            kind: 'tool_activity',
            toolName: 'write',
            arguments: { path: 'a.ts' }
          }
        ]
      },
      runningBySession: { s1: true }
    },
    's1'
  )
  assert.equal(projected.open, true)
  assert.equal(projected.usageAvailable, true)
  assert.equal(projected.model.running, true)
  assert.match(projected.model.plan, /edit composer/)
  assert.deepEqual(projected.model.files, ['a.ts'])
  assert.equal(projected.model.tokensUsed, 15)
  assert.equal(projected.model.step, 'editing')
  const html = renderToStaticMarkup(
    createElement(RunPanel, { open: projected.open, usageAvailable: projected.usageAvailable, model: projected.model })
  )
  assert.match(html, /data-testid="run-panel"/)
  assert.match(html, /data-section="plan"/)
  assert.match(html, /data-section="files"/)
  assert.match(html, /data-section="summary"/)
})

test('App mounts RunPanel in the workbench', () => {
  const app = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../../renderer/src/App.tsx'), 'utf8')
  assert.match(app, /from '..\/..\/features\/runpanel\/RunPanel.ts'/)
  assert.match(app, /<RunPanel/)
})
