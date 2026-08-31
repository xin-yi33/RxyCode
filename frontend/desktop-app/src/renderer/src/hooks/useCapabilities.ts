import { useCallback, useEffect, useState } from 'react'
import type { ProtocolClient } from '@rxycode/protocol-client'
import { parseCapabilitiesList, type CapabilityRow } from '../../../features/capabilities/capability.model.ts'

export function useCapabilities(
  client: ProtocolClient | null,
  kind: 'skill' | 'mcp'
): {
  items: CapabilityRow[]
  loading: boolean
  error: string | null
  refresh(): Promise<void>
  setEnabled(capabilityId: string, enabled: boolean): Promise<void>
} {
  const [items, setItems] = useState<CapabilityRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async (): Promise<void> => {
    if (client == null) {
      setItems([])
      setError(null)
      return
    }
    setLoading(true)
    try {
      const raw = await client.requestWithTimeout<unknown>('capabilities/list', { kind }, 10_000)
      setItems(parseCapabilitiesList(raw))
      setError(null)
    } catch (err) {
      setItems([])
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [client, kind])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const setEnabled = useCallback(
    async (capabilityId: string, enabled: boolean): Promise<void> => {
      if (client == null) return
      await client.requestWithTimeout('capabilities/set_enabled', { capability_id: capabilityId, enabled }, 10_000)
      await refresh()
    },
    [client, refresh]
  )

  return { items, loading, error, refresh, setEnabled }
}
