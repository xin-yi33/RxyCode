import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { BoardView } from './BoardView.ts'
import {
  BOARD_COLUMNS,
  canDragBetween,
  columnAllowsDrag,
  GX1_EXAMPLE_STATUSES,
  H5_THREAD_STATUSES,
  H5_TURN_STATUSES,
  mapStatusToColumn,
  projectSessionToBoardStatus,
  selectBoardColumns,
  sessionsToBoardThreads,
  showErrorBadge,
  type BoardThread
} from './board.selectors.ts'
import { boardVisualState } from './boardVisualState.ts'

const MAPPING_EXAMPLES: Array<[string, ReturnType<typeof mapStatusToColumn>]> = [
  ['drafting', 'drafts'],
  ['running', 'active'],
  ['awaiting_review', 'ready'],
  ['done', 'done']
]

test('GX1: four frozen example statuses map to Drafts/Active/Ready/Done', () => {
  for (const [status, column] of MAPPING_EXAMPLES) {
    assert.equal(mapStatusToColumn(status), column, status)
  }
})

test('GX1: H5 ThreadStatus and TurnStatus mapping is a total function', () => {
  for (const status of H5_THREAD_STATUSES) {
    assert.ok(BOARD_COLUMNS.includes(mapStatusToColumn(status)), status)
  }
  for (const status of H5_TURN_STATUSES) {
    assert.ok(BOARD_COLUMNS.includes(mapStatusToColumn(status)), status)
  }
  for (const status of GX1_EXAMPLE_STATUSES) {
    assert.ok(BOARD_COLUMNS.includes(mapStatusToColumn(status)), status)
  }
  assert.equal(mapStatusToColumn('brand_new_unknown_status'), 'active')
  assert.equal(showErrorBadge('brand_new_unknown_status'), true)
  assert.equal(showErrorBadge('failed'), true)
  assert.equal(showErrorBadge('cancelled'), true)
  assert.equal(showErrorBadge('blocked'), true)
  assert.equal(showErrorBadge('running'), false)
})

test('GX1: drag only Drafts↔Active; Ready/Done stay system-owned', () => {
  assert.equal(canDragBetween('drafts', 'active'), true)
  assert.equal(canDragBetween('active', 'drafts'), true)
  assert.equal(canDragBetween('drafts', 'ready'), false)
  assert.equal(canDragBetween('active', 'done'), false)
  assert.equal(canDragBetween('ready', 'done'), false)
  assert.equal(canDragBetween('done', 'drafts'), false)
  assert.equal(columnAllowsDrag('drafts'), true)
  assert.equal(columnAllowsDrag('active'), true)
  assert.equal(columnAllowsDrag('ready'), false)
  assert.equal(columnAllowsDrag('done'), false)
})

test('GX1: selectBoardColumns never drops a thread', () => {
  const threads: BoardThread[] = [
    { id: '1', title: 'draft', updatedAt: 1, status: 'drafting' },
    { id: '2', title: 'run', updatedAt: 2, status: 'running' },
    { id: '3', title: 'review', updatedAt: 3, status: 'awaiting_review' },
    { id: '4', title: 'done', updatedAt: 4, status: 'done' },
    { id: '5', title: 'fail', updatedAt: 5, status: 'failed' },
    { id: '6', title: 'ghost', updatedAt: 6, status: 'not-in-enum' }
  ]
  const columns = selectBoardColumns(threads)
  const all = [...columns.drafts, ...columns.active, ...columns.ready, ...columns.done]
  assert.equal(all.length, 6)
  assert.equal(columns.drafts.map((c) => c.id).join(), '1')
  assert.equal(columns.active.map((c) => c.id).join(), '2,5,6')
  assert.equal(columns.ready.map((c) => c.id).join(), '3')
  assert.equal(columns.done.map((c) => c.id).join(), '4')
  assert.equal(columns.ready[0]?.reviewEntry, true)
  assert.equal(columns.active.find((c) => c.id === '5')?.errorBadge, true)
})

test('GX1: session projection uses runState without inventing a second model', () => {
  assert.equal(projectSessionToBoardStatus({ trashed: false }), 'drafting')
  assert.equal(projectSessionToBoardStatus({ trashed: false, runState: 'running' }), 'running')
  assert.equal(projectSessionToBoardStatus({ trashed: false, runState: 'approval' }), 'awaiting_review')
  assert.equal(
    projectSessionToBoardStatus({ trashed: false, runState: 'succeeded', hasActivity: true }),
    'done'
  )
  assert.equal(projectSessionToBoardStatus({ trashed: true }), 'trashed')
  const threads = sessionsToBoardThreads(
    [
      { sessionId: 'a', title: 'A', updatedAt: 1, trashedAt: null },
      { sessionId: 'b', title: 'B', updatedAt: 2, trashedAt: 9 }
    ],
    { a: 'running' },
    { a: true }
  )
  assert.equal(threads[0]?.status, 'running')
  assert.equal(threads[1]?.status, 'trashed')
})

test('GX1: BoardView five states + four columns + review entry + click', () => {
  assert.equal(boardVisualState({ loading: true, error: null, empty: false, narrow: false, dark: false }), 'loading')
  assert.equal(boardVisualState({ loading: false, error: 'x', empty: false, narrow: false, dark: false }), 'error')
  assert.equal(boardVisualState({ loading: false, error: null, empty: true, narrow: false, dark: false }), 'empty')
  assert.equal(boardVisualState({ loading: false, error: null, empty: false, narrow: true, dark: false }), 'narrow')
  assert.equal(boardVisualState({ loading: false, error: null, empty: false, narrow: false, dark: true }), 'dark')

  const opened: string[] = []
  const threads: BoardThread[] = [
    { id: 'd1', title: 'Draft task', updatedAt: 1, status: 'drafting' },
    { id: 'r1', title: 'Need review', updatedAt: 2, status: 'awaiting_review' }
  ]
  const html = renderToStaticMarkup(
    createElement(BoardView, {
      threads,
      onOpenThread: (id: string) => {
        opened.push(id)
      }
    })
  )
  assert.match(html, /data-testid="board-view"/)
  assert.match(html, /data-testid="board-column-drafts"/)
  assert.match(html, /data-testid="board-column-active"/)
  assert.match(html, /data-testid="board-column-ready"/)
  assert.match(html, /data-testid="board-column-done"/)
  assert.match(html, /Draft task/)
  assert.match(html, /Need review/)
  assert.match(html, /data-testid="board-review-r1"/)
  assert.match(html, /data-draggable="true"/)
  assert.match(html, /data-draggable="false"/)

  const empty = renderToStaticMarkup(
    createElement(BoardView, { threads: [], onOpenThread: () => undefined })
  )
  assert.match(empty, /data-visual-state="empty"/)
  assert.match(empty, /data-testid="board-empty"/)

  const loading = renderToStaticMarkup(
    createElement(BoardView, { threads: [], loading: true, onOpenThread: () => undefined })
  )
  assert.match(loading, /data-visual-state="loading"/)
  assert.match(loading, /data-testid="board-loading"/)

  const errored = renderToStaticMarkup(
    createElement(BoardView, {
      threads: [],
      error: 'store disconnected',
      onOpenThread: () => undefined
    })
  )
  assert.match(errored, /data-visual-state="error"/)
  assert.match(errored, /store disconnected/)

  const narrow = renderToStaticMarkup(
    createElement(BoardView, {
      threads,
      narrow: true,
      onOpenThread: () => undefined
    })
  )
  assert.match(narrow, /data-visual-state="narrow"/)
  assert.match(narrow, /data-narrow="true"/)

  const dark = renderToStaticMarkup(
    createElement(BoardView, {
      threads,
      dark: true,
      onOpenThread: () => undefined
    })
  )
  assert.match(dark, /data-visual-state="dark"/)
  assert.match(dark, /data-theme="dark"/)
})
