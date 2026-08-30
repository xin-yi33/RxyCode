export type RouteMode = 'solo' | 'auto' | 'team'

export interface MultiModelSettings {
  enabled: boolean
  masterModel: string | null
  roleModels: Record<string, string>
}

export interface AgentsSettingsView {
  enabled: boolean
  team: string
  routeMode: RouteMode
  routerModel: string | null
  totalTokenBudget: number
  totalTimeoutS: number
  multiModel: MultiModelSettings
}

export function defaultAgentsSettings(): AgentsSettingsView {
  return {
    enabled: false,
    team: 'software_dev',
    routeMode: 'auto',
    routerModel: null,
    totalTokenBudget: 500_000,
    totalTimeoutS: 1800,
    multiModel: { enabled: false, masterModel: null, roleModels: {} }
  }
}

function asRouteMode(value: unknown): RouteMode {
  return value === 'solo' || value === 'team' || value === 'auto' ? value : 'auto'
}

export function parseAgentsSettings(raw: unknown): AgentsSettingsView {
  const base = defaultAgentsSettings()
  if (raw == null || typeof raw !== 'object') return base
  const data = raw as Record<string, unknown>
  const mm = (data.multi_model ?? data.multiModel) as Record<string, unknown> | undefined
  const roleRaw = (mm?.role_models ?? mm?.roleModels) as Record<string, unknown> | undefined
  const roleModels: Record<string, string> = {}
  if (roleRaw != null) {
    for (const [role, model] of Object.entries(roleRaw)) {
      if (typeof model === 'string' && model.trim() !== '') roleModels[role] = model
    }
  }
  return {
    enabled: data.enabled === true,
    team: typeof data.team === 'string' && data.team.trim() !== '' ? data.team : base.team,
    routeMode: asRouteMode(data.route_mode ?? data.routeMode),
    routerModel:
      typeof data.router_model === 'string'
        ? data.router_model
        : typeof data.routerModel === 'string'
          ? data.routerModel
          : null,
    totalTokenBudget: Number(data.total_token_budget ?? data.totalTokenBudget ?? base.totalTokenBudget) || base.totalTokenBudget,
    totalTimeoutS: Number(data.total_timeout_s ?? data.totalTimeoutS ?? base.totalTimeoutS) || base.totalTimeoutS,
    multiModel: {
      enabled: mm?.enabled === true,
      masterModel:
        typeof mm?.master_model === 'string'
          ? mm.master_model
          : typeof mm?.masterModel === 'string'
            ? mm.masterModel
            : null,
      roleModels
    }
  }
}

export function agentsSettingsVisible(view: AgentsSettingsView): {
  showParams: boolean
  showMultiModel: boolean
  showRoleModels: boolean
} {
  return {
    showParams: view.enabled,
    showMultiModel: view.enabled,
    showRoleModels: view.enabled && view.multiModel.enabled
  }
}

export function agentsSettingsSetPayload(view: AgentsSettingsView): Record<string, unknown> {
  return {
    enabled: view.enabled,
    team: view.team,
    route_mode: view.routeMode,
    router_model: view.routerModel,
    total_token_budget: view.totalTokenBudget,
    total_timeout_s: view.totalTimeoutS,
    multi_model: {
      enabled: view.multiModel.enabled,
      master_model: view.multiModel.masterModel,
      role_models: view.multiModel.roleModels
    }
  }
}
