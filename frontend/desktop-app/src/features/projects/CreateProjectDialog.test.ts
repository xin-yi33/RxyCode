import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { CreateProjectDialog } from './CreateProjectDialog.ts'
import { emptyCreateProjectDraft } from './createProject.ts'

test('create project type step matches Codex local/remote cards', () => {
  const html = renderToStaticMarkup(
    createElement(CreateProjectDialog, {
      draft: emptyCreateProjectDraft(),
      onChange: () => undefined,
      onPickFolder: () => undefined,
      onCancel: () => undefined,
      onSubmit: () => undefined
    })
  )
  assert.match(html, /data-testid="create-project-local"/)
  assert.match(html, /data-testid="create-project-remote"/)
  assert.match(html, /下一步/)
})

test('create project details step asks for name and a source folder', () => {
  const html = renderToStaticMarkup(
    createElement(CreateProjectDialog, {
      draft: { step: 'details', kind: 'local', name: '', folder: '' },
      onChange: () => undefined,
      onPickFolder: () => undefined,
      onCancel: () => undefined,
      onSubmit: () => undefined
    })
  )
  assert.match(html, /data-testid="create-project-name"/)
  assert.match(html, /data-testid="create-project-folder-path"/)
  assert.match(html, /添加 RxyCode 可读取和编辑的文件夹/)
  assert.match(html, /创建项目/)
})
