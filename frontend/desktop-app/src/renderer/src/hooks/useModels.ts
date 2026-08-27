/**
 * Phase 4 D5: model / credential management via appserver JSON-RPC.
 *
 * Talks only through the conversation-owned ProtocolClient (DC1). A single
 * renderer client owns the JSON-RPC id space and receives server requests;
 * model management must never create a second client for the same stdio
 * stream, or it could race an approval response.
 */
import { useCallback, useEffect, useState } from 'react'
import { isDeclaredCapability, type ProtocolClient } from '@rxycode/protocol-client'
import {
  classifyModelsListFailure,
  type ModelsUnavailableReason
} from '../lib/modelAvailability.mts'
import { requestSetActive } from '../../../features/settings/setActiveParams.ts'

export interface ModelEntry {
  id: string
  name: string
  nickname: string
  provider_model_id: string
  base_url: string
  active: boolean
  category: string
  provider_name: string
  provider_id: string
  max_tokens_mode?: string
  resolved_max_tokens?: number | null
  limit_source?: string
  context_window?: number | null
  warning?: string | null
  effort_options?: string[]
}

export interface ModelsSnapshot {
  models: ModelEntry[]
  active: string
  recent: string[]
  effort: string | null
}

export interface ProviderPreset {
  id: string
  name: string
  base_url: string
  category?: string
}

export interface DiscoveredModel {
  id: string
  object?: string
}

export interface OnboardResult {
  ok: boolean
  error_code?: string
  message?: string
  id?: string
  active?: string | null
  added?: string[]
  onboarded?: string[]
  failed?: Array<{ id: string; reason: string }>
}

export interface UseModelsOptions {
  client: ProtocolClient | null
  refreshKey: number
  capabilities?: Readonly<Record<string, unknown>> | null
}

export interface UseModelsResult {
  supported: boolean
  loading: boolean
  error: string | null
  unavailableReason: ModelsUnavailableReason | null
  snapshot: ModelsSnapshot | null
  refresh(): Promise<void>
  setActive(id: string, effort?: string | null): Promise<boolean>
  remove(id: string): Promise<boolean>
  upsertCredential(id: string, apiKey: string): Promise<boolean>
  deleteCredential(id: string): Promise<boolean>
  testConnection(id: string): Promise<{ ok: boolean; message: string }>
  listPresets(): Promise<ProviderPreset[]>
  discover(apiKey: string, baseUrl: string): Promise<DiscoveredModel[]>
  onboard(args: {
    providerModelId: string
    apiKey: string
    baseUrl: string
    nickname?: string
  }): Promise<OnboardResult>
  onboardBatch(args: {
    apiKey: string
    baseUrl: string
    modelIds: string[]
    skipProbe?: boolean
  }): Promise<OnboardResult>
}

export function useModels({
  client,
  refreshKey,
  capabilities = null
}: UseModelsOptions): UseModelsResult {
  const [supported, setSupported] = useState(false)
  const [loading, setLoading] = useState(() => client !== null)
  const [error, setError] = useState<string | null>(client === null ? 'appserver not connected' : null)
  const [unavailableReason, setUnavailableReason] = useState<ModelsUnavailableReason | null>(
    client === null ? 'not-connected' : null
  )
  const [snapshot, setSnapshot] = useState<ModelsSnapshot | null>(null)

  const refresh = useCallback(async () => {
    if (client === null) {
      setSupported(false)
      setSnapshot(null)
      setUnavailableReason('not-connected')
      setError('appserver not connected')
      setLoading(false)
      return
    }
    if (capabilities !== null && !isDeclaredCapability(capabilities, 'models')) {
      setSupported(false)
      setSnapshot(null)
      setUnavailableReason('method-not-found')
      setError('capability not declared: models')
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const list = (await client.requestWithTimeout(
        'models/list',
        {},
        30_000
      )) as Record<string, unknown>
      setSupported(true)
      setUnavailableReason(null)
      setSnapshot({
        models: (list.models ?? []) as ModelEntry[],
        active: String(list.active ?? ''),
        recent: (list.recent ?? []) as string[],
        effort: typeof list.effort === 'string' && list.effort !== '' ? list.effort : null
      })
    } catch (e) {
      setSupported(false)
      setSnapshot(null)
      setUnavailableReason(classifyModelsListFailure(e, true))
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [client, capabilities])

  useEffect(() => {
    void refresh()
  }, [refresh, refreshKey])

  const setActive = useCallback(
    async (id: string, effort?: string | null): Promise<boolean> => {
      if (client === null) return false
      try {
        const ok = await requestSetActive(
          (method, params, timeoutMs) => client.requestWithTimeout(method, params, timeoutMs),
          id,
          effort
        )
        if (ok) await refresh()
        return ok
      } catch {
        return false
      }
    },
    [client, refresh]
  )

  const remove = useCallback(
    async (id: string): Promise<boolean> => {
      if (client === null) return false
      try {
        const r = (await client.requestWithTimeout('models/remove', { id }, 30_000)) as {
          ok?: boolean
        }
        if (r.ok === true) await refresh()
        return r.ok === true
      } catch {
        return false
      }
    },
    [client, refresh]
  )

  const upsertCredential = useCallback(async (id: string, apiKey: string): Promise<boolean> => {
    if (client === null) return false
    try {
      const r = (await client.requestWithTimeout('credentials/upsert', { id, api_key: apiKey }, 30_000)) as {
        ok?: boolean
      }
      return r.ok === true
    } catch {
      return false
    }
  }, [client])

  const deleteCredential = useCallback(async (id: string): Promise<boolean> => {
    if (client === null) return false
    try {
      const r = (await client.requestWithTimeout('credentials/delete', { id }, 30_000)) as {
        ok?: boolean
      }
      return r.ok === true
    } catch {
      return false
    }
  }, [client])

  const testConnection = useCallback(
    async (id: string): Promise<{ ok: boolean; message: string }> => {
      if (client === null) {
        return { ok: false, message: 'appserver not connected' }
      }
      try {
        const r = (await client.requestWithTimeout('models/test_connection', { id }, 30_000)) as {
          ok?: boolean
          message?: string
        }
        return { ok: r.ok === true, message: String(r.message ?? '') }
      } catch (e) {
        return { ok: false, message: e instanceof Error ? e.message : String(e) }
      }
    },
    [client]
  )

  const listPresets = useCallback(async (): Promise<ProviderPreset[]> => {
    if (client === null) return []
    try {
      const r = (await client.requestWithTimeout('models/presets', {}, 30_000)) as {
        presets?: ProviderPreset[]
      }
      return r.presets ?? []
    } catch {
      return []
    }
  }, [client])

  const discover = useCallback(
    async (apiKey: string, baseUrl: string): Promise<DiscoveredModel[]> => {
      if (client === null) return []
      try {
        const r = (await client.requestWithTimeout(
          'models/discover',
          { api_key: apiKey, base_url: baseUrl },
          30_000
        )) as { ok?: boolean; models?: DiscoveredModel[] }
        if (r.ok === false) return []
        return r.models ?? []
      } catch {
        return []
      }
    },
    [client]
  )

  const onboard = useCallback(
    async (args: {
      providerModelId: string
      apiKey: string
      baseUrl: string
      nickname?: string
    }): Promise<OnboardResult> => {
      if (client === null) {
        return { ok: false, error_code: 'transport', message: 'appserver not connected' }
      }
      try {
        const r = (await client.requestWithTimeout(
          'models/onboard',
          {
            provider_model_id: args.providerModelId,
            api_key: args.apiKey,
            base_url: args.baseUrl,
            nickname: args.nickname
          },
          30_000
        )) as OnboardResult
        if (r.ok === true) await refresh()
        return r
      } catch (e) {
        return { ok: false, error_code: 'transport', message: e instanceof Error ? e.message : String(e) }
      }
    },
    [client, refresh]
  )

  const onboardBatch = useCallback(
    async (args: {
      apiKey: string
      baseUrl: string
      modelIds: string[]
      skipProbe?: boolean
    }): Promise<OnboardResult> => {
      if (client === null) {
        return { ok: false, error_code: 'transport', message: 'appserver not connected' }
      }
      try {
        const r = (await client.requestWithTimeout(
          'models/onboard_batch',
          {
            api_key: args.apiKey,
            base_url: args.baseUrl,
            model_ids: args.modelIds,
            skip_probe: args.skipProbe ?? true
          },
          60_000
        )) as OnboardResult
        if (r.ok === true) await refresh()
        return r
      } catch (e) {
        return { ok: false, error_code: 'transport', message: e instanceof Error ? e.message : String(e) }
      }
    },
    [client, refresh]
  )

  return {
    supported,
    loading,
    error,
    unavailableReason,
    snapshot,
    refresh,
    setActive,
    remove,
    upsertCredential,
    deleteCredential,
    testConnection,
    listPresets,
    discover,
    onboard,
    onboardBatch
  }
}
