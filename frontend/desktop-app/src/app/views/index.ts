export type DesktopViewId = 'chat' | 'board'

export interface DesktopViewEntry {
  id: DesktopViewId
  titleKey: string
  commandId: string
  shortcut: string
}

export const DESKTOP_VIEWS: readonly DesktopViewEntry[] = [
  { id: 'chat', titleKey: 'tasks', commandId: 'view.chat', shortcut: 'Ctrl+1' },
  { id: 'board', titleKey: 'boardView', commandId: 'view.board', shortcut: 'Ctrl+K' }
]

export function resolveDesktopView(id: string | null | undefined): DesktopViewEntry {
  return DESKTOP_VIEWS.find((view) => view.id === id) ?? DESKTOP_VIEWS[0]
}

export function viewFromCommand(commandId: string): DesktopViewEntry | undefined {
  return DESKTOP_VIEWS.find((view) => view.commandId === commandId)
}
