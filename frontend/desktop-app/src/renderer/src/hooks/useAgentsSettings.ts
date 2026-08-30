import { useCallback, useEffect, useState } from 'react'
import type { ProtocolClient } from '@rxycode/protocol-client'
import {
  agentsSettingsSetPayload,
  defaultAgentsSettings,
  parseAgentsSettings,
  type AgentsSettingsView
} from '../../../features/settings/agentsSettings.ts'

export function useAgentsSettings(client: ProtocolClient | null): {
  settings: AgentsSettingsView
  loading: boolean
  refresh(): Promise<void>
  save(next: AgentsSettingsView): Promise<void>
} {
  const [settings, setSettings] = useState<AgentsSettingsView>(defaultAgentsSettings)
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async (): Promise<void> => {
    if (client == null) return
    setLoading(true)
    try {
      const raw = await client.requestWithTimeout<Record<string, unknown>>('agents/settings_get', {}, 10_000)
      setSettings(parseAgentsSettings(raw))
    } catch {
      setSettings(defaultAgentsSettings())
    } finally {
      setLoading(false)
    }
  }, [client])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const save = useCallback(
    async (next: AgentsSettingsView): Promise<void> => {
      setSettings(next)
      if (client == null) return
      const raw = await client.requestWithTimeout<Record<string, unknown>>(
        'agents/settings_set',
        agentsSettingsSetPayload(next),
        10_000
      )
      setSettings(parseAgentsSettings(raw))
    },
    [client]
  )

  return { settings, loading, refresh, save }
}
