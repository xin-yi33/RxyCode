export type ProjectKind = 'local' | 'remote'
export type CreateProjectStep = 'type' | 'details'

export interface CreateProjectDraft {
  step: CreateProjectStep
  kind: ProjectKind
  name: string
  folder: string
}

export function emptyCreateProjectDraft(): CreateProjectDraft {
  return { step: 'type', kind: 'local', name: '', folder: '' }
}

export function canAdvanceProjectType(draft: CreateProjectDraft): boolean {
  return draft.kind === 'local'
}

export function canSubmitLocalProject(draft: CreateProjectDraft): boolean {
  return draft.kind === 'local' && draft.folder.trim() !== ''
}

export function projectNameFromFolder(folder: string): string {
  const cleaned = folder.replace(/[\\/]+$/, '')
  const parts = cleaned.split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] ?? ''
}
