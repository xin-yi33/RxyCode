const ROLE_FILE: Record<string, string> = {
  pm: 'member-pm.png',
  architect: 'member-architect.png',
  frontend_coder: 'member-engineer.png',
  backend_coder: 'member-engineer.png',
  tester: 'member-tester.png',
  verifier: 'member-tester.png',
  security_auditor: 'member-auditor.png',
  quality_auditor: 'member-auditor.png',
  maintainability_auditor: 'member-auditor.png',
  doc: 'member-doc.png'
}

export function teamPortraitSrc(teamId: string): string | null {
  if (teamId === 'software_dev') return 'teams/software_dev.png'
  return null
}

export function memberPortraitSrc(role: string): string | null {
  const file = ROLE_FILE[role]
  return file == null ? null : `teams/${file}`
}
