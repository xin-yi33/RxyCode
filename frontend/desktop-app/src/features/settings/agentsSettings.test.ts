import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  agentsSettingsSetPayload,
  agentsSettingsVisible,
  defaultAgentsSettings,
  parseAgentsSettings
} from './agentsSettings.ts'

test('H10 fold: params and multi-model stay hidden until the outer switch is on', () => {
  const off = defaultAgentsSettings()
  assert.deepEqual(agentsSettingsVisible(off), {
    showParams: false,
    showMultiModel: false,
    showRoleModels: false
  })
  const agentsOn = { ...off, enabled: true }
  assert.deepEqual(agentsSettingsVisible(agentsOn), {
    showParams: true,
    showMultiModel: true,
    showRoleModels: false
  })
  const bothOn = {
    ...agentsOn,
    multiModel: { ...agentsOn.multiModel, enabled: true, masterModel: 'gpt-5.6-luna' }
  }
  assert.deepEqual(agentsSettingsVisible(bothOn), {
    showParams: true,
    showMultiModel: true,
    showRoleModels: true
  })
})

test('parseAgentsSettings reads agents/settings_get and set payload uses snake_case', () => {
  const parsed = parseAgentsSettings({
    enabled: true,
    team: 'software_dev',
    route_mode: 'auto',
    router_model: null,
    total_token_budget: 120000,
    total_timeout_s: 900,
    multi_model: {
      enabled: true,
      master_model: 'gpt-5.6-luna',
      role_models: { architect: 'deepseek-v4' }
    }
  })
  assert.equal(parsed.enabled, true)
  assert.equal(parsed.multiModel.masterModel, 'gpt-5.6-luna')
  assert.equal(parsed.multiModel.roleModels.architect, 'deepseek-v4')
  const payload = agentsSettingsSetPayload(parsed)
  assert.equal((payload.multi_model as { master_model: string }).master_model, 'gpt-5.6-luna')
  assert.equal(payload.route_mode, 'auto')
}
)