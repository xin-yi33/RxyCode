import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ProtocolClient } from '@rxycode/protocol-client'
import { parseCapabilitiesList } from '../../../features/capabilities/capability.model.ts'
import { parseSkillSearch, type SkillMarketItem } from '../../../features/skills/skill.model.ts'

export function useSkillMarket(client: ProtocolClient | null): {
  installed: SkillMarketItem[]
  market: SkillMarketItem[]
  hub: SkillMarketItem[]
  loading: boolean
  error: string | null
  detail: string
  refresh(): Promise<void>
  search(query: string, source?: 'github' | 'hub'): Promise<void>
  install(input: { source: string; query?: string; url?: string; path?: string; name?: string }): Promise<string>
  loadDetail(capabilityId: string): Promise<void>
} {
  const [installedRaw, setInstalledRaw] = useState<SkillMarketItem[]>([])
  const [market, setMarket] = useState<SkillMarketItem[]>([])
  const [hub, setHub] = useState<SkillMarketItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [detail, setDetail] = useState('')

  const installedNames = useMemo(
    () => new Set(installedRaw.map((item) => item.name)),
    [installedRaw]
  )

  const refresh = useCallback(async (): Promise<void> => {
    if (client == null) {
      setInstalledRaw([])
      setError(null)
      return
    }
    setLoading(true)
    try {
      const raw = await client.requestWithTimeout<unknown>('capabilities/list', { kind: 'skill' }, 10_000)
      const rows = parseCapabilitiesList(raw)
      setInstalledRaw(
        rows.map((row) => ({
          name: row.name,
          source: 'installed',
          stars: 0,
          description: row.description,
          scope: row.scope || row.origin,
          installed: row.installed,
          path: row.origin
        }))
      )
      setError(null)
    } catch (err) {
      setInstalledRaw([])
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [client])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const search = useCallback(
    async (query: string, source: 'github' | 'hub' = 'github'): Promise<void> => {
      if (client == null) return
      setLoading(true)
      try {
        const raw = await client.requestWithTimeout<unknown>('skill/search', { query, source }, 20_000)
        const rows = parseSkillSearch(raw, installedNames)
        if (source === 'hub') setHub(rows)
        else setMarket(rows)
        setError(null)
      } catch (err) {
        if (source === 'hub') setHub([])
        else setMarket([])
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setLoading(false)
      }
    },
    [client, installedNames]
  )

  const install = useCallback(
    async (input: { source: string; query?: string; url?: string; path?: string; name?: string }): Promise<string> => {
      if (client == null) return 'no client'
      try {
        await client.requestWithTimeout('skill/install', input, 60_000)
        await refresh()
        return ''
      } catch (err) {
        return err instanceof Error ? err.message : String(err)
      }
    },
    [client, refresh]
  )

  const loadDetail = useCallback(
    async (capabilityId: string): Promise<void> => {
      if (client == null) return
      try {
        const raw = await client.requestWithTimeout<{ body?: string; description?: string }>(
          'capabilities/get',
          { capability_id: capabilityId },
          10_000
        )
        setDetail(String(raw.body ?? raw.description ?? ''))
      } catch (err) {
        setDetail(err instanceof Error ? err.message : String(err))
      }
    },
    [client]
  )

  return {
    installed: installedRaw,
    market,
    hub,
    loading,
    error,
    detail,
    refresh,
    search,
    install,
    loadDetail
  }
}
