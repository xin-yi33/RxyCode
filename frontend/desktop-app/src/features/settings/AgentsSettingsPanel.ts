import { createElement, type ReactElement } from 'react'
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
    createElement('option', { key: '', value: '' }, inherit),
    ...props.models.map((model) => createElement('option', { key: model.id, value: model.id }, model.label))
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
            createElement(
              'select',
              {
                'data-testid': 'agents-route',
                value: props.settings.routeMode,
                onChange: (event: React.ChangeEvent<HTMLSelectElement>) =>
                  props.onChange({ ...props.settings, routeMode: event.target.value as RouteMode })
              },
              createElement('option', { value: 'auto' }, props.labels.routeAuto ?? 'auto'),
              createElement('option', { value: 'solo' }, props.labels.routeSolo ?? 'solo'),
              createElement('option', { value: 'team' }, props.labels.routeTeam ?? 'team')
            )
          ),
          createElement(
            'label',
            null,
            props.labels.agentsRouterModel ?? 'Router model',
            createElement(
              'select',
              {
                'data-testid': 'agents-router-model',
                value: props.settings.routerModel ?? '',
                onChange: (event: React.ChangeEvent<HTMLSelectElement>) =>
                  props.onChange({
                    ...props.settings,
                    routerModel: event.target.value === '' ? null : event.target.value
                  })
              },
              createElement('option', { value: '' }, props.labels.routerNone ?? 'None'),
              ...props.models.map((model) => createElement('option', { key: model.id, value: model.id }, model.label))
            )
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
                  createElement(
                    'select',
                    {
                      'data-testid': 'master-model',
                      value: props.settings.multiModel.masterModel ?? '',
                      onChange: (event: React.ChangeEvent<HTMLSelectElement>) =>
                        props.onChange({
                          ...props.settings,
                          multiModel: {
                            ...props.settings.multiModel,
                            masterModel: event.target.value === '' ? null : event.target.value
                          }
                        })
                    },
                    ...modelOptions
                  )
                ),
                ...props.roles.map((role) =>
                  createElement(
                    'label',
                    { key: role },
                    role,
                    createElement(
                      'select',
                      {
                        'data-testid': `role-model-${role}`,
                        value: props.settings.multiModel.roleModels[role] ?? '',
                        onChange: (event: React.ChangeEvent<HTMLSelectElement>) => {
                          const next = { ...props.settings.multiModel.roleModels }
                          if (event.target.value === '') delete next[role]
                          else next[role] = event.target.value
                          props.onChange({
                            ...props.settings,
                            multiModel: { ...props.settings.multiModel, roleModels: next }
                          })
                        }
                      },
                      ...modelOptions
                    )
                  )
                )
              )
            : null
        )
      : null
  )
}
