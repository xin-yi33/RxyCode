import { createElement, type ReactElement } from 'react'
import { ThemeMenu } from '../composer/ThemeMenu.ts'
import { agentsSettingsVisible, type AgentsSettingsView, type RouteMode } from './agentsSettings.ts'

export interface AgentsModelOption {
  id: string
  label: string
}

export function AgentsSettingsPanel(props: {
  settings: AgentsSettingsView
  models: readonly AgentsModelOption[]
  roles: readonly string[]
  labels: Record<string, string>
  onChange: (next: AgentsSettingsView) => void
}): ReactElement {
  const visible = agentsSettingsVisible(props.settings)
  const inherit = props.labels.inheritMaster ?? 'Inherit master'
  const modelOptions = [
    { value: '', label: inherit },
    ...props.models.map((model) => ({ value: model.id, label: model.label }))
  ]
  return createElement(
    'section',
    { className: 'agents-settings', 'data-testid': 'agents-settings' },
    createElement(
      'label',
      { className: 'agents-settings-row' },
      createElement('input', {
        type: 'checkbox',
        'data-testid': 'agents-enabled',
        checked: props.settings.enabled,
        onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
          props.onChange({ ...props.settings, enabled: event.target.checked })
      }),
      props.labels.agentsEnable ?? 'Enable expert teams'
    ),
    visible.showParams
      ? createElement(
          'div',
          { className: 'agents-advanced', 'data-testid': 'agents-params' },
          createElement(
            'label',
            null,
            props.labels.agentsRoute ?? 'Route',
            createElement(ThemeMenu, {
              value: props.settings.routeMode,
              options: [
                { value: 'auto', label: props.labels.routeAuto ?? 'auto' },
                { value: 'solo', label: props.labels.routeSolo ?? 'solo' },
                { value: 'team', label: props.labels.routeTeam ?? 'team' }
              ],
              onChange: (value) => props.onChange({ ...props.settings, routeMode: value as RouteMode }),
              testId: 'agents-route',
              ariaLabel: props.labels.agentsRoute ?? 'Route',
              placement: 'down',
              align: 'end'
            })
          ),
          createElement(
            'label',
            null,
            props.labels.agentsRouterModel ?? 'Router model',
            createElement(ThemeMenu, {
              value: props.settings.routerModel ?? '',
              options: [
                { value: '', label: props.labels.routerNone ?? 'None' },
                ...props.models.map((model) => ({ value: model.id, label: model.label }))
              ],
              onChange: (value) =>
                props.onChange({
                  ...props.settings,
                  routerModel: value === '' ? null : value
                }),
              testId: 'agents-router-model',
              ariaLabel: props.labels.agentsRouterModel ?? 'Router model',
              placement: 'down',
              align: 'end'
            })
          ),
          createElement(
            'label',
            null,
            props.labels.agentsBudget ?? 'Token budget',
            createElement('input', {
              type: 'number',
              'data-testid': 'agents-budget',
              value: props.settings.totalTokenBudget,
              onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
                props.onChange({ ...props.settings, totalTokenBudget: Number(event.target.value) || 0 })
            })
          ),
          createElement(
            'label',
            { className: 'agents-settings-row' },
            createElement('input', {
              type: 'checkbox',
              'data-testid': 'multi-model-enabled',
              checked: props.settings.multiModel.enabled,
              onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
                props.onChange({
                  ...props.settings,
                  multiModel: { ...props.settings.multiModel, enabled: event.target.checked }
                })
            }),
            props.labels.multiModelEnable ?? 'Enable multi-model collaboration'
          ),
          visible.showRoleModels
            ? createElement(
                'div',
                { className: 'agents-role-models', 'data-testid': 'multi-model-roles' },
                createElement(
                  'label',
                  null,
                  props.labels.masterModel ?? 'Master model',
                  createElement(ThemeMenu, {
                    value: props.settings.multiModel.masterModel ?? '',
                    options: modelOptions,
                    onChange: (value) =>
                      props.onChange({
                        ...props.settings,
                        multiModel: {
                          ...props.settings.multiModel,
                          masterModel: value === '' ? null : value
                        }
                      }),
                    testId: 'master-model',
                    ariaLabel: props.labels.masterModel ?? 'Master model',
                    placement: 'down',
                    align: 'end'
                  })
                ),
                ...props.roles.map((role) =>
                  createElement(
                    'label',
                    { key: role },
                    role,
                    createElement(ThemeMenu, {
                      value: props.settings.multiModel.roleModels[role] ?? '',
                      options: modelOptions,
                      onChange: (value) => {
                        const next = { ...props.settings.multiModel.roleModels }
                        if (value === '') delete next[role]
                        else next[role] = value
                        props.onChange({
                          ...props.settings,
                          multiModel: { ...props.settings.multiModel, roleModels: next }
                        })
                      },
                      testId: `role-model-${role}`,
                      ariaLabel: role,
                      placement: 'down',
                      align: 'end'
                    })
                  )
                )
              )
            : null
        )
      : null
  )
}
