export const workbenchTokens = {
  canvas: '#0d0d0d',
  surface: '#000000',
  surfaceRaised: '#181818',
  hover: '#ffffff14',
  border: '#ffffff14',
  text: '#ffffff',
  muted: '#ffffffa6',
  focus: '#339cffb3',
  railWidthPx: 248,
  desktopMinPx: 1280
} as const

export function workbenchLayoutClass(input: {
  inspectorOpen: boolean
  runPanelOpen: boolean
  navOpen: boolean
  pluginHubOpen?: boolean
  bottomPanelOpen?: boolean
  snapping?: boolean
}): string {
  const parts = ['main-layout', 'command-layout']
  if (input.inspectorOpen) parts.push('inspector-open')
  if (input.runPanelOpen) parts.push('run-panel-open')
  if (input.navOpen) parts.push('navigation-open')
  if (input.pluginHubOpen === true) parts.push('plugin-hub-open')
  if (input.bottomPanelOpen === true) parts.push('bottom-panel-open')
  if (input.snapping === true) parts.push('is-snapping')
  return parts.join(' ')
}

export function sessionRailSelector(navigationDisplay: string): '.desktop-navigation-panel' | '.nav-sheet' {
  return navigationDisplay === 'none' ? '.nav-sheet' : '.desktop-navigation-panel'
}
