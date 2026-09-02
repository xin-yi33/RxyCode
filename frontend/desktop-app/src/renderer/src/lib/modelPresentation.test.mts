import { test } from 'node:test'
import assert from 'node:assert/strict'
import type { ModelEntry } from '../hooks/useModels'
import {
  duplicateModelNicknames,
  groupModelsByProvider,
  modelGroupLabel,
  modelHasCredential,
  modelPickerLabel
} from './modelPresentation.mts'

const model = (overrides: Partial<ModelEntry> = {}): ModelEntry => ({
  id: 'model-1',
  name: 'model-1',
  nickname: '',
  provider_model_id: 'model-1',
  base_url: 'https://custom.example/v1',
  active: false,
  category: '其他',
  provider_name: '其他',
  provider_id: 'custom',
  ...overrides
})

test('custom and empty provider metadata use the stable Others group', () => {
  assert.equal(modelGroupLabel(model()), 'Others')
  assert.equal(modelGroupLabel(model({ provider_name: '', provider_id: '' })), 'Others')
})

test('known provider labels stay grouped consistently across the desktop', () => {
  const grouped = groupModelsByProvider([
    model({ id: 'zen-1', provider_name: 'OpenCode Zen', provider_id: 'zen' }),
    model({ id: 'zen-2', provider_name: 'OpenCode Zen', provider_id: 'zen' }),
    model({ id: 'custom-1' })
  ])

  assert.deepEqual(grouped.map(([label, entries]) => [label, entries.map((entry) => entry.id)]), [
    ['OpenCode Zen', ['zen-1', 'zen-2']],
    ['Others', ['custom-1']]
  ])
})

test('duplicate glm-5.2 labels keep the config id; keyless models are marked', () => {
  const ark = model({
    id: 'ark/glm-5.2',
    name: 'glm-5.2',
    nickname: 'glm-5.2',
    provider_model_id: 'glm-5.2',
    warning: 'API credential is unavailable; set ARK_API_KEY or re-add the model with its API key.'
  })
  const go = model({
    id: 'opencode-go/glm-5.2',
    name: 'glm-5.2',
    nickname: 'glm-5.2',
    provider_model_id: 'glm-5.2',
    provider_id: 'opencode-go',
    provider_name: 'OpenCode Go'
  })
  const duplicates = duplicateModelNicknames([ark, go])
  assert.equal(modelHasCredential(ark), false)
  assert.equal(modelHasCredential(go), true)
  assert.equal(modelPickerLabel(ark, duplicates, '未配置密钥'), 'glm-5.2 (ark/glm-5.2) · 未配置密钥')
  assert.equal(modelPickerLabel(go, duplicates, '未配置密钥'), 'glm-5.2 (opencode-go/glm-5.2)')
})
