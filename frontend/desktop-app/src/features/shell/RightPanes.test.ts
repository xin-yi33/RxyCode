import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { BrowserPane } from './BrowserPane.ts'
import { FilesPane, knownFilesFromTimeline } from './FilesPane.ts'

test('right-pane destinations render distinct browser and files surfaces', () => {
  const browser = renderToStaticMarkup(createElement(BrowserPane, { initialUrl: '' }))
  const files = renderToStaticMarkup(
    createElement(FilesPane, {
      workspaceRoot: 'D:\\work',
      files: ['src/main.ts'],
      onReveal: () => undefined
    })
  )
  assert.match(browser, /data-testid="right-view-browser"/)
  assert.match(browser, /data-testid="browser-url"/)
  assert.match(files, /data-testid="right-view-files"/)
  assert.match(files, /src\/main.ts/)
  assert.match(files, /在资源管理器中打开/)
  const empty = renderToStaticMarkup(
    createElement(FilesPane, { workspaceRoot: 'D:\\work', files: [], onReveal: () => undefined })
  )
  assert.match(empty, /还没有文件变更/)
  assert.match(empty, /data-testid="files-empty"/)
})

test('files pane lists tool paths from the current timeline', () => {
  assert.deepEqual(
    knownFilesFromTimeline([
      { kind: 'tool_activity', arguments: { path: 'src/App.tsx' } },
      { kind: 'tool_activity', arguments: { file: 'src/App.tsx' } },
      { kind: 'tool_activity', arguments: { path: '.' } },
      { kind: 'user_prompt' }
    ]),
    ['src/App.tsx']
  )
})
