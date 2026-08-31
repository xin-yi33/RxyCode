import { useCallback, useEffect, useState } from 'react'
import type { ProtocolClient } from '@rxycode/protocol-client'
import { parsePluginList, type PluginRecord } from '../../../features/plugins/plugin.model.ts'

export function usePlugins(client: ProtocolClient | null): {
  items: PluginRecord[]
  loading: boolean
  error: string | null
  refresh(): Promise<void>
  install(input: { source: string; path?: string; name?: string }): Promise<string>
  toggle(name: string, enabled: boolean): Promise<void>
} {
  const [items, setItems] = useState<PluginRecord[]>([])
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
      const raw = await client.requestWithTimeout<unknown>('plugin/list', {}, 10_000)
      setItems(parsePluginList(raw))
      setError(null)
    } catch (err) {
      setItems([])
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [client])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const install = useCallback(
    async (input: { source: string; path?: string; name?: string }): Promise<string> => {
      if (client == null) return 'no client'
      try {
        await client.requestWithTimeout('plugin/install', input, 30_000)
        await refresh()
        return ''
      } catch (err) {
        return err instanceof Error ? err.message : String(err)
      }
    },
    [client, refresh]
  )

  const toggle = useCallback(
    async (name: string, enabled: boolean): Promise<void> => {
      if (client == null) return
      await client.requestWithTimeout('plugin/toggle', { name, enabled }, 10_000)
      await refresh()
    },
    [client, refresh]
  )

  return { items, loading, error, refresh, install, toggle }
}
