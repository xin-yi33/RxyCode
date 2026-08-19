import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { ReadOnlyLock } from './ReadOnlyLock.ts'
import { SessionListFilter } from './SessionListFilter.ts'
import { configLocked, filterSessions, groupByProject } from './sessionFilter.ts'

test('GX11: running locks config/history but composer stays for GX5', () => {
  assert.equal(configLocked('running'), true)
  assert.equal(configLocked('done'), false)
  const lock = renderToStaticMarkup(createElement(ReadOnlyLock, { status: 'running' }))
  assert.match(lock, /data-locked="true"/)
  assert.match(lock, /running/)
})

test('GX11: status x project filter and grouping', () => {
  const sessions = [
    { id: '1', title: 'a', status: 'running' as const, projectId: 'p1' },
    { id: '2', title: 'b', status: 'done' as const, projectId: 'p1' },
    { id: '3', title: 'c', status: 'running' as const, projectId: 'p2' }
  ]
  assert.equal(filterSessions(sessions, { status: 'running', projectId: 'p1' }).map((s) => s.id).join(), '1')
  assert.deepEqual(Object.keys(groupByProject(sessions)).sort(), ['p1', 'p2'])
  const html = renderToStaticMarkup(
    createElement(SessionListFilter, {
      status: 'all',
      projectId: '',
      onStatus: () => undefined,
      onProject: () => undefined
    })
  )
  assert.match(html, /data-testid="session-list-filter"/)
})
