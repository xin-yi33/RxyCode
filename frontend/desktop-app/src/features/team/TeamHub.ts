import { createElement, type ReactElement } from 'react'

export type TeamHubTab = 'gallery' | 'create' | 'settings'

export function TeamHubNav(props: {
  tab: TeamHubTab
  labels: { gallery: string; create: string; settings: string }
  onChange: (tab: TeamHubTab) => void
}): ReactElement {
  const items: Array<[TeamHubTab, string, string]> = [
    ['gallery', 'team-hub-gallery', props.labels.gallery],
    ['create', 'team-hub-create', props.labels.create],
    ['settings', 'team-hub-settings', props.labels.settings]
  ]
  return createElement(
    'nav',
    { className: 'team-hub-nav', 'data-testid': 'team-hub-nav' },
    ...items.map(([id, testId, label]) =>
      createElement(
        'button',
        {
          key: id,
          type: 'button',
          className: 'team-hub-tab' + (props.tab === id ? ' is-active' : ''),
          'data-testid': testId,
          onClick: () => props.onChange(id)
        },
        label
      )
    )
  )
}
