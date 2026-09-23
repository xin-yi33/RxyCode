export interface VersionCardModel {
  version: number
  turnId: string
  summary: string
  fileCount: number
}

export function versionsFromTurns(
  turns: readonly { turnId: string; summary: string; fileCount: number }[]
): VersionCardModel[] {
  return turns.map((turn, index) => ({
    version: index + 1,
    turnId: turn.turnId,
    summary: turn.summary,
    fileCount: turn.fileCount
  }))
}
