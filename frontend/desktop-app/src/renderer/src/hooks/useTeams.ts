import { useCallback, useEffect, useState } from 'react'
import type { ProtocolClient } from '@rxycode/protocol-client'
import type { TeamGroup, TeamRecord } from '../../../features/team/team.visual.ts'
import { firstTeamIdInGroup, mapTeamGroups, mapTeamListItem } from '../../../features/team/team.model.ts'

export interface UseTeamsResult {
  teams: TeamRecord[]
  groups: TeamGroup[]
  activeTeamId: string | null
  loading: boolean
  error: string | null
  refresh(): Promise<void>
  setActive(teamId: string): Promise<boolean>
  renameGroup(oldId: string, nextName: string): Promise<boolean>
  install(input: { name: string; url?: string; confirm?: boolean; group?: string }): Promise<string>
  activateGroup(groupId: string): Promise<boolean>
}

export function useTeams(
  client: ProtocolClient | null,
  sessionId: string | null
): UseTeamsResult {
  const [teams, setTeams] = useState<TeamRecord[]>([])
  const [groups, setGroups] = useState<TeamGroup[]>([])
  const [activeTeamId, setActiveTeamId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async (): Promise<void> => {
    if (client == null) return
    setLoading(true)
    try {
      const [list, groupResult] = await Promise.all([
        client.requestWithTimeout<{ teams?: Array<Record<string, unknown>> }>('team/list', {}, 10_000),
        client.requestWithTimeout<{ groups?: Array<Record<string, unknown>> }>('team/groups', {}, 10_000)
      ])
      const mappedGroups = mapTeamGroups(groupResult.groups ?? [])
      const groupByTeam = new Map<string, string>()
      for (const group of mappedGroups) {
        for (const member of group.members ?? []) groupByTeam.set(member, group.id)
      }
      setGroups(mappedGroups)
      setTeams(
        (list.teams ?? []).map((item) =>
          mapTeamListItem(item, groupByTeam.get(String(item.id ?? item.name ?? '')) ?? 'other')
        )
      )
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [client])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const setActive = useCallback(
    async (teamId: string): Promise<boolean> => {
      if (client == null || sessionId == null || sessionId === '') return false
      const result = await client.requestWithTimeout<{ ok?: boolean; active?: string }>(
        'team/set_active',
        { session_id: sessionId, team_id: teamId },
        10_000
      )
      if (result.ok === false) return false
      setActiveTeamId(result.active ?? teamId)
      return true
    },
    [client, sessionId]
  )

  const renameGroup = useCallback(
    async (oldId: string, nextName: string): Promise<boolean> => {
      if (client == null) return false
      const result = await client.requestWithTimeout<{ ok?: boolean }>('team/group_rename', { old: oldId, new: nextName }, 10_000)
      if (result.ok === false) return false
      await refresh()
      return true
    },
    [client, refresh]
  )

  const install = useCallback(
    async (input: { name: string; url?: string; confirm?: boolean; group?: string }): Promise<string> => {
      if (client == null) return ''
      const result = await client.requestWithTimeout<{ message?: string }>(
        'team/install',
        {
          name: input.name,
          url: input.url ?? '',
          confirm: input.confirm === true,
          group: input.group ?? ''
        },
        30_000
      )
      if (input.confirm === true) await refresh()
      return String(result.message ?? '')
    },
    [client, refresh]
  )

  const activateGroup = useCallback(
    async (groupId: string): Promise<boolean> => {
      const teamId = firstTeamIdInGroup(teams, groupId)
      if (teamId == null) return false
      return setActive(teamId)
    },
    [setActive, teams]
  )

  return {
    teams,
    groups,
    activeTeamId,
    loading,
    error,
    refresh,
    setActive,
    renameGroup,
    install,
    activateGroup
  }
}
