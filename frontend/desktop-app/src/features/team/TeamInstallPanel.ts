import { createElement, useState, type ReactElement } from 'react'
import type { TeamGroup } from './team.visual.ts'

export function TeamInstallPanel(props: {
  groups: readonly TeamGroup[]
  onInstall: (groupId: string) => void
}): ReactElement {
  const [step, setStep] = useState<'confirm' | 'group'>('confirm')
  const [groupId, setGroupId] = useState('other')
  return createElement(
    'section',
    { className: 'team-install', 'data-testid': 'team-install-panel', 'data-step': step },
    step === 'confirm'
      ? createElement(
          'div',
          null,
          createElement('p', null, 'Install this team?'),
          createElement('button', { type: 'button', onClick: () => setStep('group') }, 'Confirm install')
        )
      : createElement(
          'div',
          null,
          createElement(
            'select',
            {
              'aria-label': 'Install group',
              value: groupId,
              onChange: (event: React.ChangeEvent<HTMLSelectElement>) => setGroupId(event.target.value)
            },
            createElement('option', { value: 'other' }, 'other'),
            ...props.groups.map((group) => createElement('option', { key: group.id, value: group.id }, group.name))
          ),
          createElement('button', { type: 'button', onClick: () => props.onInstall(groupId) }, 'Finish install')
        )
  )
}
