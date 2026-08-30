import type { TeamGroup, TeamMemberView, TeamRecord, TeamStageView } from './team.visual.ts'

export type { TeamMemberView, TeamStageView }

export const CREATE_TEAM_PROMPT = `我想创建一个新的专家团。请逐步和我确认：1) 团名与分类 2) 成员（角色 id、职位、一句话职责，团长居首）3) 阶段流程。确认后：在 ~/.RxyCode/teams/<团名>/ 生成 team.yaml 与 prompts/<角色>.md（遵循 core/agents/teams/software_dev 的结构），然后调用 team_install 工具注册，最后汇报注册结果。`

export function extraValue(extra: Record<string, unknown> | undefined, key: string): unknown {
  if (extra == null) return undefined
  if (key in extra) return extra[key]
  const dotted = key.includes('.') ? extra[key] : extra[`ecosystem.${key}`]
  return dotted
}

export function isLeaderMember(
  member: { extra?: Record<string, unknown>; role?: string },
  index: number,
  hasExplicitLeader = false
): boolean {
  const extra = member.extra ?? {}
  const flag = extra['ecosystem.is_leader'] ?? extra.is_leader
  if (flag === true || flag === 'true' || flag === 1) return true
  if (hasExplicitLeader) return false
  return index === 0 && flag !== false
}

export function leaderFirstMembers(members: readonly TeamMemberView[]): TeamMemberView[] {
  const leaders = members.filter((member) => member.isLeader)
  const rest = members.filter((member) => !member.isLeader)
  return [...leaders, ...rest]
}

export function examplePromptsFromExtra(extra: Record<string, unknown> | undefined): string[] {
  const raw =
    extraValue(extra, 'example_prompts') ??
    extraValue(extra, 'ecosystem.example_prompts') ??
    extraValue(extra, 'try_prompts')
  if (Array.isArray(raw)) {
    return raw.map((item) => String(item).trim()).filter((item) => item !== '')
  }
  if (typeof raw === 'string' && raw.trim() !== '') return [raw.trim()]
  return []
}

export function mapTeamListItem(raw: Record<string, unknown>, groupId = 'other'): TeamRecord {
  const extra = (raw.extra as Record<string, unknown> | undefined) ?? {}
  const membersRaw = Array.isArray(raw.members) ? raw.members : []
  const stagesRaw = Array.isArray(raw.stages) ? raw.stages : []
  const hasExplicitLeader = membersRaw.some((item) => {
    const extra = ((item ?? {}) as Record<string, unknown>).extra as Record<string, unknown> | undefined
    const flag = extra?.['ecosystem.is_leader'] ?? extra?.is_leader
    return flag === true || flag === 'true' || flag === 1
  })
  const members = leaderFirstMembers(
    membersRaw.map((item, index) => {
      const member = (item ?? {}) as Record<string, unknown>
      const memberExtra = (member.extra as Record<string, unknown> | undefined) ?? {}
      return {
        role: String(member.role ?? ''),
        displayName: String(member.display_name ?? member.displayName ?? member.role ?? ''),
        title: typeof member.title === 'string' ? member.title : undefined,
        isLeader: isLeaderMember({ extra: memberExtra, role: String(member.role ?? '') }, index, hasExplicitLeader)
      }
    })
  )
  return {
    id: String(raw.id ?? raw.name ?? ''),
    name: String(raw.display_name ?? raw.displayName ?? raw.name ?? raw.id ?? ''),
    groupId: String(raw.group ?? raw.group_id ?? groupId),
    description: typeof raw.description === 'string' ? raw.description : typeof raw.summary === 'string' ? raw.summary : undefined,
    summary: typeof raw.summary === 'string' ? raw.summary : undefined,
    extra,
    members,
    stages: stagesRaw.map((item) => {
      const stage = (item ?? {}) as Record<string, unknown>
      return { name: String(stage.name ?? ''), role: String(stage.role ?? '') }
    }),
    examplePrompts: examplePromptsFromExtra(extra),
    disableModelInvocation: extra['ecosystem.disable_model_invocation'] === true
  }
}

export function mapTeamGroups(rawGroups: readonly Record<string, unknown>[]): TeamGroup[] {
  return rawGroups.map((group) => ({
    id: String(group.id ?? group.name ?? ''),
    name: String(group.name ?? group.id ?? ''),
    builtin: group.builtin === true,
    members: Array.isArray(group.members) ? group.members.map((item) => String(item)) : []
  }))
}

export function firstTeamIdInGroup(teams: readonly TeamRecord[], groupId: string): string | null {
  return teams.find((team) => team.groupId === groupId)?.id ?? null
}
