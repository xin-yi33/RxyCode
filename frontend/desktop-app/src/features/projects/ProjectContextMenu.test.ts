import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { ProjectContextMenu } from './ProjectContextMenu.ts'

test('Codex project overflow menu matches pin edit section explorer worktree archive remove', () => {
  const html = renderToStaticMarkup(
    createElement(ProjectContextMenu, {
      x: 20,
      y: 40,
      pinned: false,
      labels: {
        pin: '置顶',
        unpin: '取消置顶',
        edit: '编辑',
        section: '分区',
        reveal: '在资源管理器中打开',
        createWorktree: '创建永久工作树',
        archiveChats: '归档聊天',
        removeProject: '移除项目',
        recent: '最近'
      },
      onAction: () => undefined,
      onClose: () => undefined
    })
  )
  assert.match(html, /data-testid="project-context-menu"/)
  assert.match(html, /置顶/)
  assert.match(html, /编辑/)
  assert.match(html, /分区/)
  assert.match(html, /在资源管理器中打开/)
  assert.match(html, /创建永久工作树/)
  assert.match(html, /归档聊天/)
  assert.match(html, /移除项目/)
  assert.match(html, /is-danger/)
})
