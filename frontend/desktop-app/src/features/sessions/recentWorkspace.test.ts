import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import {
  composerProjectChip,
  defaultRecentWorkspace,
  isRecentWorkspace,
  resolveCreateSessionWorkspace,
  resolveRecentHome,
  workspaceForNewChat
} from './recentWorkspace.ts'

test('recent workspace is ~/.RxyCode and empty roots count as recent', () => {
  assert.equal(defaultRecentWorkspace('C:/Users/me'), 'C:/Users/me/.RxyCode')
  assert.equal(isRecentWorkspace('', 'C:/Users/me/.RxyCode'), true)
  assert.equal(isRecentWorkspace('C:\\Users\\me\\.RxyCode', 'C:/Users/me/.RxyCode'), true)
  assert.equal(isRecentWorkspace('C:/Users/me/.rxycode', 'C:/Users/me/.RxyCode'), true)
  assert.equal(isRecentWorkspace('D:/agent-demo/RxyCode-phase-g-integrate', 'C:/Users/me/.RxyCode'), false)
})

test('new chat without a project stays in recent; a picked folder becomes the workspace', () => {
  assert.equal(
    workspaceForNewChat({ selectedProject: null, recentHome: 'C:/Users/me/.RxyCode' }),
    'C:/Users/me/.RxyCode'
  )
  assert.equal(
    workspaceForNewChat({ selectedProject: 'D:/papers', recentHome: 'C:/Users/me/.RxyCode' }),
    'D:/papers'
  )
})

test('recent home never falls back to a repo root', () => {
  assert.equal(resolveRecentHome('C:/Users/me'), 'C:/Users/me/.RxyCode')
  assert.equal(resolveRecentHome('', 'C:/Users/alt'), 'C:/Users/alt/.RxyCode')
  assert.equal(resolveRecentHome(''), '')
  assert.equal(
    resolveCreateSessionWorkspace({
      requested: '',
      homeDir: '',
      repoRoot: 'D:/agent-demo/RxyCode-phase-g-integrate'
    }),
    ''
  )
  assert.equal(
    resolveCreateSessionWorkspace({
      requested: '   ',
      homeDir: 'C:/Users/me',
      repoRoot: 'D:/repo'
    }),
    'C:/Users/me/.RxyCode'
  )
  assert.equal(
    resolveCreateSessionWorkspace({
      requested: 'D:/papers',
      homeDir: 'C:/Users/me',
      repoRoot: 'D:/repo'
    }),
    'D:/papers'
  )
})

test('composer project chip: draft asks to pick a project; started recent chats hide it', () => {
  assert.deepEqual(
    composerProjectChip({ hasActiveSession: false, draftWorkspace: null, activeWorkspace: '' }),
    { visible: true }
  )
  assert.deepEqual(
    composerProjectChip({ hasActiveSession: false, draftWorkspace: '', activeWorkspace: '' }),
    { visible: true }
  )
  assert.deepEqual(
    composerProjectChip({
      hasActiveSession: false,
      draftWorkspace: 'C:/Users/me/.RxyCode',
      activeWorkspace: ''
    }),
    { visible: true }
  )
  assert.deepEqual(
    composerProjectChip({
      hasActiveSession: false,
      draftWorkspace: 'D:/papers',
      activeWorkspace: ''
    }),
    { visible: true, projectRoot: 'D:/papers' }
  )
  assert.deepEqual(
    composerProjectChip({
      hasActiveSession: true,
      draftWorkspace: null,
      activeWorkspace: 'C:/Users/me/.RxyCode'
    }),
    { visible: false }
  )
  assert.deepEqual(
    composerProjectChip({
      hasActiveSession: true,
      draftWorkspace: 'D:/papers',
      activeWorkspace: 'D:/papers'
    }),
    { visible: true, projectRoot: 'D:/papers' }
  )
})

test('App and createSession never send a recent draft to the opened repo', () => {
  const root = dirname(fileURLToPath(import.meta.url))
  const app = readFileSync(join(root, '../../renderer/src/App.tsx'), 'utf8')
  const conversation = readFileSync(join(root, '../../renderer/src/hooks/useConversation.ts'), 'utf8')
  assert.doesNotMatch(app, /recentHome === '' \? \(info\?\.repoRoot/)
  assert.doesNotMatch(app, /:\s*tr\('recent'\)/)
  assert.match(app, /composerProjectChip/)
  assert.match(conversation, /resolveCreateSessionWorkspace/)
  assert.doesNotMatch(
    conversation,
    /workspaceRootOverride \?\? currentInfo\.repoRoot/
  )
  const header = readFileSync(join(root, '../../renderer/src/components/TaskHeader.tsx'), 'utf8')
  assert.match(header, /looksRecentWorkspace/)
  assert.match(header, /showWorkspace/)
  assert.match(header, /data-testid="task-workspace"/)
  assert.match(app, /draftModelId/)
  assert.match(app, /setDraftModelId\(modelId\)/)
})

