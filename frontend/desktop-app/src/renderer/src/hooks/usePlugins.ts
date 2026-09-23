import { useCallback, useEffect, useState } from 'react'
import type { ProtocolClient } from '@rxycode/protocol-client'
import { parsePluginList, type PluginRecord } from '../../../features/plugins/plugin.model.ts'

export function usePlugins(client: ProtocolClient | null): {
  items: PluginRecord[]
  catalog: PluginRecord[]
  loading: boolean
  error: string | null
  refresh(): Promise<void>
  install(input: { source: string; path?: string; name?: string; token?: string }): Promise<string>
  startConnect(name: string): Promise<string>
  toggle(name: string, enabled: boolean): Promise<void>
} {
  const [items, setItems] = useState<PluginRecord[]>([])
  const [catalog, setCatalog] = useState<PluginRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async (): Promise<void> => {
    if (client == null) {
      setItems([])
      setCatalog([])
      setError(null)
      return
    }
    setLoading(true)
    try {
      const raw = await client.requestWithTimeout<unknown>('plugin/list', {}, 10_000)
      setItems(parsePluginList(raw))
      try {
        const store = await client.requestWithTimeout<unknown>('plugin/catalog', {}, 10_000)
        setCatalog(parsePluginList(store))
      } catch {
        setCatalog([])
      }
      setError(null)
    } catch (err) {
      setItems([])
      setCatalog([])
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [client])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const install = useCallback(
    async (input: { source: string; path?: string; name?: string; token?: string }): Promise<string> => {
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

  const startConnect = useCallback(
    async (name: string): Promise<string> => {
      if (client == null) return 'no client'
      try {
        const raw = await client.requestWithTimeout<{ authorize_url?: string }>(
          'plugin/connect/start',
          { name },
          30_000
        )
        const url = typeof raw?.authorize_url === 'string' ? raw.authorize_url : ''
        if (url !== '' && typeof window !== 'undefined' && typeof window.open === 'function') {
          window.open(url, '_blank', 'noopener,noreferrer')
        }
        await refresh()
        return url
      } catch (err) {
        return err instanceof Error ? err.message : String(err)
      }
    },
    [client, refresh]
  )

  return { items, catalog, loading, error, refresh, install, startConnect, toggle }
}
