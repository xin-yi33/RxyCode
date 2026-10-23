// BYOK 目录的共享查询（PRD §7.2）。查询键约定：
//   ["models"]            → GET /models（Composer 选择器 + 设置共用）
//   ["modelConnections"]  → GET /model-connections
//   ["modelsAccess"]      → GET /models/access（require_byok/平台授权/密钥环）
//   ["modelProviders"]    → GET /models/providers（预设，基本不变）
// 访客态一律 enabled:false —— 私有目录对未登录身份不发请求。
import { useQuery, type QueryClient } from "@tanstack/react-query"

import { createClient } from "../../sdk/client"

const api = createClient()

export function useModelsCatalog(enabled = true) {
  return useQuery({
    queryKey: ["models"],
    queryFn: ({ signal }) => api.listModels(signal),
    enabled,
    staleTime: 30_000,
  })
}

export function useModelConnections(enabled = true) {
  return useQuery({
    queryKey: ["modelConnections"],
    queryFn: ({ signal }) => api.listModelConnections(signal),
    enabled,
    staleTime: 30_000,
  })
}

export function useModelsAccess(enabled = true) {
  return useQuery({
    queryKey: ["modelsAccess"],
    queryFn: ({ signal }) => api.getModelsAccess(signal),
    enabled,
    staleTime: 60_000,
  })
}

export function useModelProviders(enabled = true) {
  return useQuery({
    queryKey: ["modelProviders"],
    queryFn: ({ signal }) => api.listModelProviders(signal),
    enabled,
    staleTime: 300_000,
  })
}

// 写操作后统一失效（预设不刷 —— 服务端常量）。
export function invalidateModelQueries(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: ["models"] })
  void queryClient.invalidateQueries({ queryKey: ["modelConnections"] })
  void queryClient.invalidateQueries({ queryKey: ["modelsAccess"] })
}
