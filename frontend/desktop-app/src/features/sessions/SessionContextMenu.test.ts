import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { SessionContextMenu } from './SessionContextMenu.ts'

test('Codex session context menu lists pin rename unread archive and new window', () => {
  const html = renderToStaticMarkup(
    createElement(SessionContextMenu, {
      x: 20,
      y: 40,
      pinned: false,
      unread: false,
      sessionId: 's1',
      title: 'hello',
      currentProject: null,
      projects: [{ cwd: 'D:/work', displayName: 'work' }],
      labels: {
        pin: '置顶',
        unpin: '取消置顶',
        rename: '重命名',
        unread: '标记为未读',
        archive: '归档',
        project: '项目',
        section: '分区',
        share: '分享',
        copy: '复制',
        copyTitle: '复制标题',
        copyId: '复制 ID',
        openInNewWindow: '在新窗口中打开',
        recent: '最近'
      },
      onAction: () => undefined,
      onClose: () => undefined
    })
  )
  assert.match(html, /data-testid="session-context-menu"/)
  assert.match(html, /置顶/)
  assert.match(html, /重命名/)
  assert.match(html, /标记为未读/)
  assert.match(html, /归档/)
  assert.match(html, /项目/)
  assert.match(html, /分区/)
  assert.match(html, /分享/)
  assert.match(html, /复制/)
  assert.match(html, /在新窗口中打开/)
  assert.match(html, /Alt\+Ctrl\+P/)
  assert.match(html, /Alt\+Ctrl\+R/)
  assert.match(html, /Ctrl\+Shift\+U/)
  assert.match(html, /Ctrl\+Shift\+A/)
  assert.match(html, /data-testid="ctx-share"/)
})
