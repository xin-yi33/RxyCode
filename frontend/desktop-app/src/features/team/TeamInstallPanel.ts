import { createElement, useState, type ReactElement } from 'react'
import type { TeamGroup } from './team.visual.ts'

export type TeamInstallSource = 'directory' | 'zip' | 'github'
export type TeamInstallStep = 'source' | 'confirm' | 'group'

export const TEAM_PACK_HINT = '这是专家团队包（team.yaml + 角色），不是纯 skill 包。'
export const TEAM_HOOKS_WARNING = '第三方 hooks 默认禁用。确认安装不会自动开启 hooks。'

export function TeamInstallPanel(props: {
  groups: readonly TeamGroup[]
  preview?: { message?: string; hooks?: boolean; members?: number } | null
  labels?: {
    source?: string
    directory?: string
    zip?: string
    github?: string
    confirm?: string
    finish?: string
  }
  onPreview?: (source: TeamInstallSource, value: string) => void
  onInstall: (input: { groupId: string; source: TeamInstallSource; value: string }) => void
}): ReactElement {
  const [step, setStep] = useState<TeamInstallStep>('source')
  const [source, setSource] = useState<TeamInstallSource>('directory')
  const [value, setValue] = useState('')
  const [groupId, setGroupId] = useState('other')
  const labels = props.labels ?? {}
  return createElement(
    'section',
    { className: 'team-install', 'data-testid': 'team-install-panel', 'data-step': step },
    step === 'source'
      ? createElement(
          'div',
          null,
          createElement('p', { 'data-testid': 'team-pack-hint' }, TEAM_PACK_HINT),
          createElement(
            'fieldset',
            { 'data-testid': 'team-install-source' },
            createElement('legend', null, labels.source ?? 'Import source'),
            (['directory', 'zip', 'github'] as const).map((kind) =>
              createElement(
                'label',
                { key: kind },
                createElement('input', {
                  type: 'radio',
                  name: 'team-install-source',
                  value: kind,
                  checked: source === kind,
                  onChange: () => setSource(kind)
                }),
                kind === 'directory' ? (labels.directory ?? 'Local directory') : kind === 'zip' ? (labels.zip ?? 'Zip file') : (labels.github ?? 'GitHub URL')
              )
            )
          ),
          createElement('input', {
            'data-testid': 'team-install-path',
            'aria-label': 'Install path or URL',
            value,
            placeholder: source === 'github' ? 'https://github.com/org/team' : source === 'zip' ? '/path/to/team.zip' : '/path/to/team',
            onChange: (event: React.ChangeEvent<HTMLInputElement>) => setValue(event.target.value)
          }),
          createElement(
            'button',
            {
              type: 'button',
              'data-testid': 'team-install-preview',
              disabled: value.trim() === '',
              onClick: () => {
                props.onPreview?.(source, value.trim())
                setStep('confirm')
              }
            },
            'Preview install'
          )
        )
      : null,
    step === 'confirm'
      ? createElement(
          'div',
          null,
          createElement('p', { 'data-testid': 'team-pack-hint' }, TEAM_PACK_HINT),
          createElement('p', { 'data-testid': 'team-hooks-warning' }, TEAM_HOOKS_WARNING),
          props.preview?.message != null
            ? createElement('p', { 'data-testid': 'team-install-preview-message' }, props.preview.message)
            : createElement('p', null, 'Install this team?'),
          createElement(
            'button',
            { type: 'button', 'data-testid': 'team-install-confirm', onClick: () => setStep('group') },
            labels.confirm ?? 'Confirm install'
          )
        )
      : null,
    step === 'group'
      ? createElement(
          'div',
          null,
          createElement(
            'select',
            {
              'aria-label': 'Install group',
              'data-testid': 'team-install-group',
              value: groupId,
              onChange: (event: React.ChangeEvent<HTMLSelectElement>) => setGroupId(event.target.value)
            },
            createElement('option', { value: 'other' }, 'other'),
            ...props.groups.map((group) => createElement('option', { key: group.id, value: group.id }, group.name))
          ),
          createElement(
            'button',
            {
              type: 'button',
              'data-testid': 'team-install-finish',
              onClick: () => props.onInstall({ groupId, source, value: value.trim() })
            },
            labels.finish ?? 'Finish install'
          )
        )
      : null
  )
}
