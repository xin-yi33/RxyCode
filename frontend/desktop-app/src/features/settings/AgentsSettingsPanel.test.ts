import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { AgentsSettingsPanel } from './AgentsSettingsPanel.ts'
import { defaultAgentsSettings } from './agentsSettings.ts'

const labels = {
  agentsEnable: '启用多 Agent 专家团',
  multiModelEnable: '启用多模型协作',
  masterModel: 'Master 模型',
  inheritMaster: '继承 Master'
}

test('AgentsSettingsPanel folds role dropdowns until both switches are on', () => {
  const off = renderToStaticMarkup(
    createElement(AgentsSettingsPanel, {
      settings: defaultAgentsSettings(),
      models: [{ id: 'm1', label: 'm1' }],
      roles: ['architect'],
      labels,
      onChange: () => undefined
    })
  )
  assert.match(off, /agents-enabled/)
  assert.doesNotMatch(off, /data-testid="agents-params"/)
  const params = renderToStaticMarkup(
    createElement(AgentsSettingsPanel, {
      settings: { ...defaultAgentsSettings(), enabled: true },
      models: [{ id: 'm1', label: 'm1' }],
      roles: ['architect'],
      labels,
      onChange: () => undefined
    })
  )
  assert.match(params, /agents-params/)
  assert.doesNotMatch(params, /data-testid="multi-model-roles"/)
  const roles = renderToStaticMarkup(
    createElement(AgentsSettingsPanel, {
      settings: {
        ...defaultAgentsSettings(),
        enabled: true,
        multiModel: { enabled: true, masterModel: 'm1', roleModels: {} }
      },
      models: [{ id: 'm1', label: 'm1' }],
      roles: ['architect', 'coder'],
      labels,
      onChange: () => undefined
    })
  )
  assert.match(roles, /multi-model-roles/)
  assert.match(roles, /role-model-architect/)
  assert.match(roles, /role-model-coder/)
})
