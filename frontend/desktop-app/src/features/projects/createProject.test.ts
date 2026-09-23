import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  canAdvanceProjectType,
  canSubmitLocalProject,
  emptyCreateProjectDraft,
  projectNameFromFolder
} from './createProject.ts'

test('create project walks type then local folder like Codex', () => {
  const draft = emptyCreateProjectDraft()
  assert.equal(draft.step, 'type')
  assert.equal(canAdvanceProjectType(draft), true)
  assert.equal(canAdvanceProjectType({ ...draft, kind: 'remote' }), false)
  assert.equal(canSubmitLocalProject(draft), false)
  assert.equal(canSubmitLocalProject({ ...draft, folder: 'D:/papers' }), true)
  assert.equal(projectNameFromFolder('D:/papers/论文 2'), '论文 2')
})
