export type Capabilities = {
  mode: string
  password: boolean
  registration: "invite" | "open" | "closed"
  github: boolean
  local: boolean
  password_reset?: boolean
  reset_delivery?: "smtp" | "inline" | "operator-log" | "none"
  code_delivery?: "smtp" | "inline" | "operator-log" | "none"
  captcha?: "altcha"
}

export type Me = {
  user: {
    id: string
    kind: string
    email: string | null
    display_name: string | null
    github_id: string | null
  }
  organization: { id: string; tenant_id: string }
  membership: { role: string }
  default_project_id: string | null
}

export type Project = { id: string; name: string } & Partial<ProjectItem>

export type RunAccepted = {
  run_id: string
  status: string
  session_id: string
  events_url: string
}

// 提交时解析的模型快照回显（api/runs.py::_run_model_json）；历史 run 为 null。
export type RunModel = {
  model_ref: string
  model_id: string
  provider_id: string
  provider_name: string
  credential_source: string
  display_name?: string
}

export type RunSummary = {
  run_id: string
  status: string
  created_at: string | null
  message: string
  permission_profile: string
  final_preview: string
  model?: RunModel | null
}

// GET /runs/{id} 的实际字段（api/runs.py::get_run）——没有 final_preview。
export type RunDetail = {
  run_id: string
  status: string
  session_id: string
  event_seq: number
  created_at: string | null
  message: string
  permission_profile: string
  model?: RunModel | null
}

// ---- BYOK（PRD §7.2，api/models.py） ---------------------------------------

export type ProviderPreset = {
  id: string
  name: string
  base_url: string
  category?: string
}

export type ModelsAccess = {
  require_byok: boolean
  platform_allowed: boolean
  byok_available: boolean
  default_model_ref: string | null
}

export type ModelConnection = {
  id: string
  provider_id: string
  provider_name: string
  display_name: string
  base_url: string
  api_transport: string
  has_key: boolean
  credential_version: number
  state: string
  test_status: "untested" | "ok" | "failed" | string
  test_error: string | null
  tested_at: string | null
  updated_at: string | null
  model_count: number
}

export type DiscoveredModel = {
  id: string
  name?: string
  added?: boolean
} & Record<string, unknown>

export type DiscoverResult = {
  success: boolean
  models: DiscoveredModel[]
  error: string | null
  error_code: string | null
  elapsed?: number | null
}

export type AddModelResult = {
  model_id: string
  status: "added" | "exists" | "invalid" | string
  model_ref?: string
}

export type ConnectionTestResult = {
  success: boolean
  provider_name: string
  model_id: string | null
  elapsed?: number | null
  error: string | null
  error_code: string | null
  test_status: string
}

export type ModelItem = {
  model_ref: string
  model_id: string
  display_name: string
  provider_id: string
  provider_name: string
  connection_id: string
  connection_name: string
  source: "byok" | "platform" | string
  status: "available" | "revoked" | "no_key" | string
}

export type ModelsCatalog = {
  models: ModelItem[]
  default_model_ref: string | null
}

export type SessionListItem = {
  id: string
  title: string
  project_id: string
  project_name?: string | null
  is_default_project?: boolean
  created_at?: string | null
  updated_at: string | null
  archived_at?: string | null
  archived?: boolean
  origin?: "local" | "cloud" | string
  source?: "chat" | "scheduled" | string
  pinned?: boolean
  pin_order?: number | null
  revision?: number
  last_run: { run_id: string; status: string } | null
  can_execute?: boolean
  blocked_reason?: string
}

export type SessionListResponse = {
  sessions: SessionListItem[]
  next_cursor: string | null
}

export type SessionListQuery = {
  archived?: "false" | "true" | "all"
  pinned?: "true" | "false"
  project_id?: string
  origin?: "all" | "local" | "cloud"
  source?: "all" | "chat" | "scheduled"
  sort?: "updated_at" | "created_at" | "title" | "manual"
  q?: string
  cursor?: string
  limit?: number
}

export type ProjectItem = {
  id: string
  name: string
  tenant_id: string
  memory_mode?: string
  is_default?: boolean
  pinned?: boolean
  pin_order?: number | null
  revision?: number
  created_at?: string | null
  instructions?: string
}

export type SearchHit = {
  id: string
  type: "chat" | "image" | "document" | "project"
  title: string
  snippet: string
  highlights: number[][]
  updated_at: string | null
  session_id: string | null
  project_id: string | null
  archived: boolean
  href: string
  preview: { content_type?: string; size?: number } | null
}

export type SearchResponse = {
  query: string
  type: string
  hits: SearchHit[]
  next_cursor: string | null
}

export type AppearanceProfile = {
  theme_id?: string
  accent?: string
  background?: string
  foreground?: string
  ui_font_px?: number
  code_font_px?: number
  // APP-14：0–100 视觉差异强度（默认45）；旧枚举值由服务端归一化为数值。
  contrast?: number | "normal" | "high"
}

export type Preferences = {
  revision: number
  locale: "auto" | "zh-CN" | "en" | string
  sidebar: {
    grouping: "project" | "merged"
    sort: "updated_at" | "manual"
    show_projects: boolean
    projects_collapsed?: boolean
    recent_collapsed?: boolean
  }
  appearance: {
    mode: "system" | "light" | "dark"
    separate_modes: boolean
    shared: AppearanceProfile
    light: AppearanceProfile | null
    dark: AppearanceProfile | null
    reduced_motion: "system" | "on" | "off"
    diff_markers: "color" | "symbols"
  }
}

export type ScheduleRule =
  | { kind: "interval"; every: number; unit: "minutes" | "hours" | "days" }
  | { kind: "at"; time: string; once?: boolean }
  | { kind: "weekly"; weekdays: number[]; time: string }

export type Schedule = {
  id: string
  name: string
  project_id: string
  session_id: string
  message: string
  rule: ScheduleRule
  timezone: string
  model_ref: string | null
  permission_profile: string
  enabled: boolean
  notify: boolean
  next_fire: string | null
  next_occurrences: string[]
  last_execution: {
    id: string
    scheduled_for: string | null
    status: string
    reason: string
    run_id: string | null
  } | null
  revision: number
  blocked_reason: string
  created_at: string | null
}

export type ScheduleExecution = {
  id: string
  schedule_id: string
  scheduled_for: string | null
  schedule_revision: number
  run_id: string | null
  status: string
  reason: string
  notification_status: string
  notification_id?: string | null
  email?: { id: string; status: string } | null
  run_status?: string | null
}

export type NotificationCategory = {
  id: string
  label: string
  available: boolean
  reason: string
  allowed_channels: string[]
  selected_channels: string[]
  description?: string
}

export type NotificationPreferences = {
  revision: number
  categories: NotificationCategory[]
  email_delivery: string
  push_capability: { available: boolean; reason: string }
}

export type NotificationItem = {
  id: string
  run_id: string
  kind: string
  status: string
  body: string
  title: string
  category: string
  delivery: string
  read: boolean
  created_at: string | null
  tenant_id: string
}

export type SecurityOverview = {
  password_present: boolean
  passkeys_count: number
  totp_enabled: boolean
  sms_enabled: boolean
  active_sessions_count: number
  authorized_apps_count: number
  capabilities: Record<string, { available: boolean; reason: string }>
}

export type AuthSessionItem = {
  id: string
  created_at: string | null
  last_seen_at: string | null
  expires_at: string | null
  device_label: string
  ip_hint: string
  current: boolean
  revoked: boolean
}

export type SecurityEventItem = {
  id: string
  type: string
  at: string | null
  result: string
  device_label: string
  ip_hint: string
}

export type PasskeyItem = {
  id: string
  name: string
  created_at: string | null
  last_used_at: string | null
  transports: string[]
}

// 单设备契约（后端冻结）：GET /auth/device 返回持有状态；
// 409 + DEVICE_IN_USE 时 POST /auth/device/claim 把使用权切到本设备。
export type DeviceStatus = {
  status: "active" | "held_elsewhere" | "none" | string
}

export type DeviceClaimResult = {
  claimed: boolean
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: string

  constructor(status: number, code: string, detail = "") {
    super(code)
    this.name = "ApiError"
    this.status = status
    this.code = code
    this.detail = detail
  }
}

async function readJson(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(path, {
    signal,
    credentials: "same-origin",
    headers: { accept: "application/json" },
  })
  if (!response.ok) {
    let code = "UNAVAILABLE"
    let detail = ""
    try {
      // FastAPI HTTPException 的 detail 也是错误码（如 APPROVAL_STALE）。
      const body = (await response.json()) as {
        code?: string
        reason?: string
        detail?: string
      }
      if (body.code) code = body.code
      else if (typeof body.detail === "string" && body.detail) code = body.detail
      if (body.reason) detail = body.reason
    } catch {
      code = "UNAVAILABLE"
    }
    throw new ApiError(response.status, code, detail)
  }
  return response.json()
}

// W9-F1: CSRF token is cached in memory (it is also set as the rxy_csrf
// cookie by GET /auth/csrf). A 403 FORBIDDEN clears the cache and retries
// the write once, which covers cookie rotation mid-session.
let csrfToken: string | null = null

export function resetCsrfCache(): void {
  csrfToken = null
}

async function fetchCsrfToken(force = false): Promise<string> {
  if (csrfToken && !force) return csrfToken
  const body = (await readJson("/api/v1/auth/csrf")) as { csrf_token?: string }
  csrfToken = String(body.csrf_token ?? "")
  return csrfToken
}

async function writeJson(
  path: string,
  body: unknown,
  extra: Record<string, string> = {},
  method = "POST",
): Promise<unknown> {
  let token = await fetchCsrfToken()
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        "x-csrf-token": token,
        ...extra,
      },
      body: JSON.stringify(body),
    })
    if (response.status === 403 && attempt === 0) {
      let code = ""
      try {
        const payload = (await response.json()) as { code?: string }
        code = String(payload.code ?? "")
      } catch {
        code = ""
      }
      if (code === "FORBIDDEN") {
        token = await fetchCsrfToken(true)
        continue
      }
      throw new ApiError(403, code || "FORBIDDEN")
    }
    if (!response.ok) {
      let code = "UNAVAILABLE"
      let detail = ""
      try {
        const payload = (await response.json()) as {
          code?: string
          reason?: string
          detail?: string
        }
        if (payload.code) code = payload.code
        else if (typeof payload.detail === "string" && payload.detail) {
          code = payload.detail
        }
        if (payload.reason) detail = payload.reason
      } catch {
        code = "UNAVAILABLE"
      }
      throw new ApiError(response.status, code, detail)
    }
    if (response.status === 204) return undefined
    return response.json()
  }
  throw new ApiError(403, "FORBIDDEN")
}

export type SessionInfo = {
  id: string
  title: string
  project_id: string
  updated_at?: string | null
  last_run?: { run_id: string; status: string } | null
}

// GET /api/v1/version 的构建戳（免登录）。
export type BuildStamp = {
  commit: string
  built_at: string
}

export type SessionFile = {
  path: string
  size: number
  mtime: number
}

export function createClient() {
  return {
    getVersion(signal?: AbortSignal): Promise<BuildStamp> {
      return readJson("/api/v1/version", signal) as Promise<BuildStamp>
    },
    getMe(signal?: AbortSignal): Promise<Me> {
      return readJson("/api/v1/me", signal) as Promise<Me>
    },
    getCapabilities(signal?: AbortSignal): Promise<Capabilities> {
      return readJson("/api/v1/auth/capabilities", signal) as Promise<Capabilities>
    },
    register(body: {
      email: string
      password: string
      invite_code?: string
      display_name?: string
      code?: string
      captcha?: string
    }): Promise<Me> {
      return writeJson("/api/v1/auth/register", body) as Promise<Me>
    },
    login(input: {
      email: string
      password?: string
      code?: string
      captcha?: string
    }): Promise<Me> {
      return writeJson("/api/v1/auth/login", input) as Promise<Me>
    },
    requestRegisterCode(body: {
      email: string
      captcha?: string
    }): Promise<{ ok: boolean; delivery?: string; dev_code?: string }> {
      return writeJson("/api/v1/auth/register/code", body) as Promise<{
        ok: boolean
        delivery?: string
        dev_code?: string
      }>
    },
    requestLoginCode(body: {
      email: string
      captcha?: string
    }): Promise<{ ok: boolean; delivery?: string; dev_code?: string }> {
      return writeJson("/api/v1/auth/login/code", body) as Promise<{
        ok: boolean
        delivery?: string
        dev_code?: string
      }>
    },
    logout(): Promise<void> {
      return writeJson("/api/v1/auth/logout", {}).then(() => undefined)
    },
    localLogin(secret: string): Promise<Me> {
      return writeJson("/api/v1/auth/local/login", {}, {
        "x-local-secret": secret,
      }) as Promise<Me>
    },
    getDeviceStatus(signal?: AbortSignal): Promise<DeviceStatus> {
      return readJson("/api/v1/auth/device", signal) as Promise<DeviceStatus>
    },
    claimDevice(): Promise<DeviceClaimResult> {
      return writeJson("/api/v1/auth/device/claim", {}) as Promise<DeviceClaimResult>
    },
    forgotPassword(input: {
      email: string
      captcha?: string
    }): Promise<{ ok: boolean; reset_url?: string; delivery?: string }> {
      return writeJson("/api/v1/auth/forgot", input) as Promise<{
        ok: boolean
        reset_url?: string
        delivery?: string
      }>
    },
    resetPassword(input: {
      token?: string
      email?: string
      code?: string
      password: string
    }): Promise<{ ok: boolean }> {
      return writeJson("/api/v1/auth/reset", input) as Promise<{
        ok: boolean
      }>
    },
    listProjects(signal?: AbortSignal): Promise<Project[]> {
      return readJson("/api/v1/projects", signal).then((body) => {
        const record = body as { projects?: Project[] }
        return record.projects ?? []
      })
    },
    createProject(name: string, repoConfig: Record<string, string>): Promise<Project> {
      return writeJson("/api/v1/projects", {
        name,
        repo_config: repoConfig,
      }).then((body) => (body as { project: ProjectItem }).project as Project)
    },
    createSession(projectId: string, title: string): Promise<SessionInfo> {
      const path = `/api/v1/projects/${encodeURIComponent(projectId)}/sessions`
      return writeJson(path, { title }) as Promise<SessionInfo>
    },
    createTask(body: {
      message: string
      request_id: string
      permission_profile: "confirm" | "full"
      project_id?: string
      // "platform" 哨兵或 "m_…" 目录引用；null/缺省 = 服务端默认链。
      model_ref?: string | null
    }): Promise<RunAccepted> {
      return writeJson("/api/v1/tasks", body) as Promise<RunAccepted>
    },
    createRun(
      sessionId: string,
      body: {
        message: string
        request_id: string
        permission_profile: "confirm" | "full"
        model_ref?: string | null
      },
    ): Promise<RunAccepted> {
      const path = `/api/v1/sessions/${encodeURIComponent(sessionId)}/runs`
      return writeJson(path, body) as Promise<RunAccepted>
    },
    listSessions(
      query: SessionListQuery | AbortSignal = {},
      signal?: AbortSignal,
    ): Promise<SessionListResponse> {
      // Back-compat: a bare AbortSignal means "the plain first page".
      const params = query instanceof AbortSignal ? {} : query
      const sig = query instanceof AbortSignal ? query : signal
      const qs = new URLSearchParams()
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null && value !== "") {
          qs.set(key, String(value))
        }
      }
      return readJson(`/api/v1/sessions?${qs}`, sig).then((body) => {
        const record = body as SessionListResponse
        return { sessions: record.sessions ?? [], next_cursor: record.next_cursor ?? null }
      })
    },
    patchSession(
      sessionId: string,
      body: {
        title?: string
        pinned?: boolean
        project_id?: string
        expected_revision?: number
      },
    ): Promise<{ session: SessionListItem }> {
      const path = `/api/v1/sessions/${encodeURIComponent(sessionId)}`
      return writeJson(path, body, {}, "PATCH") as Promise<{ session: SessionListItem }>
    },
    archiveSession(
      sessionId: string,
      body: { expected_revision?: number },
    ): Promise<{ session: SessionListItem; paused_schedule_count: number }> {
      const path = `/api/v1/sessions/${encodeURIComponent(sessionId)}/archive`
      return writeJson(path, body) as Promise<{
        session: SessionListItem
        paused_schedule_count: number
      }>
    },
    unarchiveSession(
      sessionId: string,
      body: { expected_revision?: number },
    ): Promise<{ session: SessionListItem; paused_schedule_count: number }> {
      const path = `/api/v1/sessions/${encodeURIComponent(sessionId)}/unarchive`
      return writeJson(path, body) as Promise<{
        session: SessionListItem
        paused_schedule_count: number
      }>
    },
    deleteSession(
      sessionId: string,
      body: { expected_revision?: number; confirm: boolean },
    ): Promise<void> {
      const path = `/api/v1/sessions/${encodeURIComponent(sessionId)}`
      return writeJson(path, body, {}, "DELETE").then(() => undefined)
    },
    patchProject(
      projectId: string,
      body: {
        name?: string
        pinned?: boolean
        instructions?: string
        expected_revision?: number
      },
    ): Promise<{ project: ProjectItem }> {
      const path = `/api/v1/projects/${encodeURIComponent(projectId)}`
      return writeJson(path, body, {}, "PATCH") as Promise<{ project: ProjectItem }>
    },
    deleteProject(
      projectId: string,
      body: { expected_revision?: number; keep_sessions?: boolean },
    ): Promise<void> {
      const path = `/api/v1/projects/${encodeURIComponent(projectId)}`
      return writeJson(path, body, {}, "DELETE").then(() => undefined)
    },
    getProject(projectId: string, signal?: AbortSignal): Promise<{ project: ProjectItem }> {
      const path = `/api/v1/projects/${encodeURIComponent(projectId)}`
      return readJson(path, signal) as Promise<{ project: ProjectItem }>
    },
    createProjectEx(body: {
      name: string
      memory_mode?: string
      request_id?: string
      repo_config?: Record<string, unknown>
    }): Promise<{ project: ProjectItem }> {
      return writeJson("/api/v1/projects", body) as Promise<{ project: ProjectItem }>
    },
    putSidebarOrder(body: {
      scope: "pinned_sessions" | "projects" | "project_sessions" | "recent"
      project_id?: string
      ordered_ids: string[]
      expected_revision?: number
    }): Promise<{ updated: boolean }> {
      return writeJson("/api/v1/me/sidebar-order", body, {}, "PUT") as Promise<{
        updated: boolean
      }>
    },
    search(
      query: { q?: string; type?: string; archived?: string; project_id?: string; cursor?: string; limit?: number },
      signal?: AbortSignal,
    ): Promise<SearchResponse> {
      const qs = new URLSearchParams()
      for (const [key, value] of Object.entries(query)) {
        if (value !== undefined && value !== null && value !== "") {
          qs.set(key, String(value))
        }
      }
      return readJson(`/api/v1/search?${qs}`, signal) as Promise<SearchResponse>
    },
    getPreferences(signal?: AbortSignal): Promise<Preferences> {
      return readJson("/api/v1/me/preferences", signal) as Promise<Preferences>
    },
    patchPreferences(body: {
      locale?: string
      sidebar?: Partial<Preferences["sidebar"]>
      appearance?: Partial<Preferences["appearance"]>
      expected_revision?: number
    }): Promise<Preferences> {
      return writeJson("/api/v1/me/preferences", body, {}, "PATCH") as Promise<Preferences>
    },
    listSchedules(
      query: { filter?: string; project_id?: string; cursor?: string; limit?: number } = {},
      signal?: AbortSignal,
    ): Promise<{ schedules: Schedule[]; next_cursor: string | null }> {
      const qs = new URLSearchParams()
      for (const [key, value] of Object.entries(query)) {
        if (value !== undefined && value !== null && value !== "") qs.set(key, String(value))
      }
      return readJson(`/api/v1/schedules?${qs}`, signal) as Promise<{
        schedules: Schedule[]
        next_cursor: string | null
      }>
    },
    getSchedule(scheduleId: string, signal?: AbortSignal): Promise<{ schedule: Schedule }> {
      const path = `/api/v1/schedules/${encodeURIComponent(scheduleId)}`
      return readJson(path, signal) as Promise<{ schedule: Schedule }>
    },
    listScheduleExecutions(
      scheduleId: string,
      query: { cursor?: string; limit?: number } = {},
      signal?: AbortSignal,
    ): Promise<{ executions: ScheduleExecution[]; next_cursor: string | null }> {
      const qs = new URLSearchParams()
      if (query.cursor) qs.set("cursor", query.cursor)
      if (query.limit) qs.set("limit", String(query.limit))
      const path = `/api/v1/schedules/${encodeURIComponent(scheduleId)}/executions?${qs}`
      return readJson(path, signal) as Promise<{
        executions: ScheduleExecution[]
        next_cursor: string | null
      }>
    },
    createSchedule(body: {
      project_id: string
      session_id: string
      rule: ScheduleRule
      name?: string
      message: string
      timezone?: string
      model_ref?: string | null
      permission_profile?: string
      notify?: boolean
      enabled?: boolean
      request_id?: string
    }): Promise<{ schedule: Schedule }> {
      return writeJson("/api/v1/schedules", body) as Promise<{ schedule: Schedule }>
    },
    patchSchedule(
      scheduleId: string,
      body: Partial<{
        name: string
        message: string
        rule: ScheduleRule
        timezone: string
        model_ref: string | null
        permission_profile: string
        notify: boolean
        enabled: boolean
        expected_revision: number
      }>,
    ): Promise<{ schedule: Schedule }> {
      const path = `/api/v1/schedules/${encodeURIComponent(scheduleId)}`
      return writeJson(path, body, {}, "PATCH") as Promise<{ schedule: Schedule }>
    },
    deleteSchedule(scheduleId: string): Promise<void> {
      const path = `/api/v1/schedules/${encodeURIComponent(scheduleId)}`
      return writeJson(path, {}, {}, "DELETE").then(() => undefined)
    },
    runScheduleNow(
      scheduleId: string,
      body: { request_id?: string; expected_revision?: number; allow_billable: boolean },
    ): Promise<RunAccepted> {
      const path = `/api/v1/schedules/${encodeURIComponent(scheduleId)}/run-now`
      return writeJson(path, body) as Promise<RunAccepted>
    },
    getNotificationPreferences(signal?: AbortSignal): Promise<NotificationPreferences> {
      return readJson("/api/v1/me/notification-preferences", signal) as Promise<NotificationPreferences>
    },
    patchNotificationPreferences(body: {
      category_id: string
      selected_channels: string[]
      expected_revision?: number
    }): Promise<NotificationPreferences> {
      const path = "/api/v1/me/notification-preferences"
      return writeJson(path, body, {}, "PATCH") as Promise<NotificationPreferences>
    },
    listNotifications(
      query: { category?: string; unread?: string; cursor?: string; limit?: number } = {},
      signal?: AbortSignal,
    ): Promise<{ notifications: NotificationItem[]; next_cursor: string | null }> {
      const qs = new URLSearchParams()
      for (const [key, value] of Object.entries(query)) {
        if (value !== undefined && value !== null && value !== "") qs.set(key, String(value))
      }
      return readJson(`/api/v1/notifications?${qs}`, signal) as Promise<{
        notifications: NotificationItem[]
        next_cursor: string | null
      }>
    },
    markNotificationRead(id: string, read = true): Promise<{ id: string; read: boolean }> {
      const path = `/api/v1/notifications/${encodeURIComponent(id)}/read`
      return writeJson(path, { read }) as Promise<{ id: string; read: boolean }>
    },
    retryNotificationEmail(id: string): Promise<{ delivery_id: string; status: string }> {
      const path = `/api/v1/notifications/${encodeURIComponent(id)}/retry-email`
      return writeJson(path, {}) as Promise<{ delivery_id: string; status: string }>
    },
    addPushSubscription(subscription: {
      endpoint: string
      expirationTime?: number | null
      keys: { p256dh: string; auth: string }
    }): Promise<{ subscription_id: string }> {
      return writeJson("/api/v1/me/push-subscriptions", { subscription }) as Promise<{
        subscription_id: string
      }>
    },
    deletePushSubscription(subscriptionId: string): Promise<void> {
      return writeJson(
        "/api/v1/me/push-subscriptions",
        { subscription_id: subscriptionId },
        {},
        "DELETE",
      ).then(() => undefined)
    },
    getSecurityOverview(signal?: AbortSignal): Promise<SecurityOverview> {
      return readJson("/api/v1/auth/security", signal) as Promise<SecurityOverview>
    },
    reauthenticate(body: {
      method: string
      purpose: string
      password?: string
    }): Promise<{ reauth_token: string; expires_at: string | null }> {
      return writeJson("/api/v1/auth/reauthenticate", body) as Promise<{
        reauth_token: string
        expires_at: string | null
      }>
    },
    listAuthSessions(
      signal?: AbortSignal,
    ): Promise<{ sessions: AuthSessionItem[]; next_cursor: string | null }> {
      return readJson("/api/v1/auth/sessions", signal) as Promise<{
        sessions: AuthSessionItem[]
        next_cursor: string | null
      }>
    },
    revokeAuthSession(id: string, reauthToken: string): Promise<void> {
      const path = `/api/v1/auth/sessions/${encodeURIComponent(id)}`
      return writeJson(path, { reauth_token: reauthToken }, {}, "DELETE").then(() => undefined)
    },
    revokeAllAuthSessions(body: {
      reauth_token: string
      include_current?: boolean
    }): Promise<{ revoked: number }> {
      return writeJson("/api/v1/auth/sessions/revoke-all", body) as Promise<{
        revoked: number
      }>
    },
    listSecurityEvents(
      signal?: AbortSignal,
    ): Promise<{ events: SecurityEventItem[]; next_cursor: string | null }> {
      return readJson("/api/v1/auth/security-events", signal) as Promise<{
        events: SecurityEventItem[]
        next_cursor: string | null
      }>
    },
    changePassword(body: { new_password: string; reauth_token: string }): Promise<void> {
      return writeJson("/api/v1/auth/password", body, {}, "PUT").then(() => undefined)
    },
    listPasskeys(
      signal?: AbortSignal,
    ): Promise<{ capability: { available: boolean; reason: string }; passkeys: PasskeyItem[] }> {
      return readJson("/api/v1/auth/passkeys", signal) as Promise<{
        capability: { available: boolean; reason: string }
        passkeys: PasskeyItem[]
      }>
    },
    totpSetup(reauthToken: string): Promise<{ setup_id: string; otpauth_uri: string; secret: string }> {
      return writeJson("/api/v1/auth/mfa/totp/setup", { reauth_token: reauthToken }) as Promise<{
        setup_id: string
        otpauth_uri: string
        secret: string
      }>
    },
    totpConfirm(setupId: string, code: string): Promise<{ enabled: boolean; backup_codes: string[] }> {
      return writeJson("/api/v1/auth/mfa/totp/confirm", {
        setup_id: setupId,
        code,
      }) as Promise<{ enabled: boolean; backup_codes: string[] }>
    },
    totpDelete(reauthToken: string, code: string): Promise<void> {
      return writeJson(
        "/api/v1/auth/mfa/totp",
        { reauth_token: reauthToken, code },
        {},
        "DELETE",
      ).then(() => undefined)
    },
    regenRecoveryCodes(reauthToken: string): Promise<{ backup_codes: string[] }> {
      return writeJson("/api/v1/auth/mfa/recovery-codes", {
        reauth_token: reauthToken,
      }) as Promise<{ backup_codes: string[] }>
    },
    // W12: session-workspace files (agent-created artifacts on the shared volume).
    listSessionFiles(sessionId: string, signal?: AbortSignal): Promise<SessionFile[]> {
      const path = `/api/v1/sessions/${encodeURIComponent(sessionId)}/files`
      return readJson(path, signal).then((body) => {
        const record = body as { files?: SessionFile[] }
        return record.files ?? []
      })
    },
    sessionFileUrl(sessionId: string, path: string): string {
      const q = new URLSearchParams({ path })
      return `/api/v1/sessions/${encodeURIComponent(sessionId)}/files/download?${q}`
    },
    getSession(sessionId: string, signal?: AbortSignal): Promise<SessionListItem> {
      const path = `/api/v1/sessions/${encodeURIComponent(sessionId)}`
      return readJson(path, signal) as Promise<SessionListItem>
    },
    listSessionRuns(
      sessionId: string,
      options: { limit?: number; before?: string } = {},
      signal?: AbortSignal,
    ): Promise<{ runs: RunSummary[]; next_cursor: string | null }> {
      const query = new URLSearchParams()
      if (options.limit) query.set("limit", String(options.limit))
      if (options.before) query.set("before", options.before)
      const path = `/api/v1/sessions/${encodeURIComponent(sessionId)}/runs?${query}`
      return readJson(path, signal) as Promise<{
        runs: RunSummary[]
        next_cursor: string | null
      }>
    },
    getRun(runId: string, signal?: AbortSignal): Promise<RunDetail> {
      const path = `/api/v1/runs/${encodeURIComponent(runId)}`
      return readJson(path, signal) as Promise<RunDetail>
    },
    githubStart(): Promise<{ authorization_url: string; state: string }> {
      return readJson("/api/v1/auth/github/start") as Promise<{
        authorization_url: string
        state: string
      }>
    },
    finishGithub(state: string, code: string): Promise<Me> {
      const query = new URLSearchParams({ state, code })
      return readJson(`/api/v1/auth/github/callback?${query}`) as Promise<Me>
    },
    workspaceTree(projectId: string, path = ""): Promise<{
      target_id: string
      entries: { name: string; type: string }[]
      changes: string[]
      pr_status: string
    }> {
      const query = new URLSearchParams({ path })
      const url = `/api/v1/workspaces/${encodeURIComponent(projectId)}/tree?${query}`
      return readJson(url) as Promise<{
        target_id: string
        entries: { name: string; type: string }[]
        changes: string[]
        pr_status: string
      }>
    },
    workspaceDiff(projectId: string, path: string): Promise<{
      path: string
      base_revision: string
      before: string
      after: string
      hunks: { id: string; header: string; lines: string[] }[]
    }> {
      const query = new URLSearchParams({ path })
      const url = `/api/v1/workspaces/${encodeURIComponent(projectId)}/diff?${query}`
      return readJson(url) as Promise<{
        path: string
        base_revision: string
        before: string
        after: string
        hunks: { id: string; header: string; lines: string[] }[]
      }>
    },
    reviewHunk(
      projectId: string,
      body: { path: string; hunk_id: string; decision: string; base_revision: string },
    ): Promise<{ status: string; base_revision: string }> {
      const url = `/api/v1/workspaces/${encodeURIComponent(projectId)}/review`
      return writeJson(url, body) as Promise<{ status: string; base_revision: string }>
    },
    listApprovals(runId: string, signal?: AbortSignal): Promise<{
      approvals: {
        approval_id: string
        call_id?: string
        tool: string
        permission_scope?: string
        arguments?: Record<string, unknown>
        status?: string
        deadline?: string | null
        revision: number
      }[]
    }> {
      const path = `/api/v1/runs/${encodeURIComponent(runId)}/approvals`
      return readJson(path, signal) as Promise<{
        approvals: {
          approval_id: string
          call_id?: string
          tool: string
          permission_scope?: string
          arguments?: Record<string, unknown>
          status?: string
          deadline?: string | null
          revision: number
        }[]
      }>
    },
    decideApproval(
      runId: string,
      body: { approval_id: string; decision: string; revision: number },
    ): Promise<{ status: string; revision: number }> {
      const path = `/api/v1/runs/${encodeURIComponent(runId)}/approvals`
      return writeJson(path, body) as Promise<{ status: string; revision: number }>
    },
    listQuestions(runId: string, signal?: AbortSignal): Promise<{
      questions: {
        question_id: string
        prompt: string
        header?: string
        options?: { label: string; value: string }[]
      }[]
    }> {
      const path = `/api/v1/runs/${encodeURIComponent(runId)}/questions`
      return readJson(path, signal) as Promise<{
        questions: {
          question_id: string
          prompt: string
          header?: string
          options?: { label: string; value: string }[]
        }[]
      }>
    },
    answerQuestion(
      runId: string,
      body: { question_id: string; answer: string },
    ): Promise<{ status: string }> {
      const path = `/api/v1/runs/${encodeURIComponent(runId)}/questions`
      return writeJson(path, body) as Promise<{ status: string }>
    },
    listArtifacts(runId: string, signal?: AbortSignal): Promise<{
      artifacts: { artifact_id: string; sha256: string; size: number; content_type: string }[]
    }> {
      const path = `/api/v1/runs/${encodeURIComponent(runId)}/artifacts`
      return readJson(path, signal) as Promise<{
        artifacts: { artifact_id: string; sha256: string; size: number; content_type: string }[]
      }>
    },
    cancelRun(runId: string): Promise<{ status: string }> {
      const path = `/api/v1/runs/${encodeURIComponent(runId)}/cancel`
      return writeJson(path, {}) as Promise<{ status: string }>
    },
    steerRun(runId: string, text: string): Promise<{ status: string }> {
      const path = `/api/v1/runs/${encodeURIComponent(runId)}/steer`
      return writeJson(path, { text }) as Promise<{ status: string }>
    },
    cancelRunChild(runId: string, sessionId: string): Promise<{ status: string }> {
      const path =
        `/api/v1/runs/${encodeURIComponent(runId)}` +
        `/children/${encodeURIComponent(sessionId)}/cancel`
      return writeJson(path, {}) as Promise<{ status: string }>
    },
    openRunEvents(runId: string): EventSource {
      return new EventSource(`/api/v1/runs/${encodeURIComponent(runId)}/events`)
    },
    // ---- BYOK：服务商预设 / 连接 / 模型目录 -----------------------------
    listModelProviders(signal?: AbortSignal): Promise<{ providers: ProviderPreset[] }> {
      return readJson("/api/v1/models/providers", signal) as Promise<{
        providers: ProviderPreset[]
      }>
    },
    getModelsAccess(signal?: AbortSignal): Promise<ModelsAccess> {
      return readJson("/api/v1/models/access", signal) as Promise<ModelsAccess>
    },
    listModelConnections(signal?: AbortSignal): Promise<{ connections: ModelConnection[] }> {
      return readJson("/api/v1/model-connections", signal) as Promise<{
        connections: ModelConnection[]
      }>
    },
    createModelConnection(body: {
      preset_id?: string
      provider_name?: string
      base_url?: string
      display_name?: string
      api_key: string
    }): Promise<{ connection: ModelConnection }> {
      return writeJson("/api/v1/model-connections", body) as Promise<{
        connection: ModelConnection
      }>
    },
    patchModelConnection(
      connectionId: string,
      body: { display_name?: string; base_url?: string; api_key?: string },
    ): Promise<{ connection: ModelConnection }> {
      const path = `/api/v1/model-connections/${encodeURIComponent(connectionId)}`
      return writeJson(path, body, {}, "PATCH") as Promise<{
        connection: ModelConnection
      }>
    },
    clearModelConnectionKey(connectionId: string): Promise<{ connection: ModelConnection }> {
      const path =
        `/api/v1/model-connections/${encodeURIComponent(connectionId)}/clear-key`
      return writeJson(path, {}) as Promise<{ connection: ModelConnection }>
    },
    deleteModelConnection(connectionId: string): Promise<{ deleted: boolean }> {
      const path = `/api/v1/model-connections/${encodeURIComponent(connectionId)}`
      return writeJson(path, {}, {}, "DELETE") as Promise<{ deleted: boolean }>
    },
    discoverConnectionModels(connectionId: string): Promise<DiscoverResult> {
      const path =
        `/api/v1/model-connections/${encodeURIComponent(connectionId)}/discover`
      return writeJson(path, {}) as Promise<DiscoverResult>
    },
    addConnectionModels(
      connectionId: string,
      modelIds: string[],
    ): Promise<{ results: AddModelResult[] }> {
      const path =
        `/api/v1/model-connections/${encodeURIComponent(connectionId)}/models`
      return writeJson(path, { model_ids: modelIds }) as Promise<{
        results: AddModelResult[]
      }>
    },
    testModelConnection(
      connectionId: string,
      body: { model_id?: string; allow_billable: boolean },
    ): Promise<ConnectionTestResult> {
      const path = `/api/v1/model-connections/${encodeURIComponent(connectionId)}/test`
      return writeJson(path, body) as Promise<ConnectionTestResult>
    },
    listModels(signal?: AbortSignal): Promise<ModelsCatalog> {
      return readJson("/api/v1/models", signal) as Promise<ModelsCatalog>
    },
    setDefaultModel(modelRef: string | null): Promise<{ default_model_ref: string | null }> {
      return writeJson("/api/v1/models/default", { model_ref: modelRef }) as Promise<{
        default_model_ref: string | null
      }>
    },
    deleteModel(modelRef: string): Promise<{ deleted: boolean }> {
      const path = `/api/v1/models/${encodeURIComponent(modelRef)}`
      return writeJson(path, {}, {}, "DELETE") as Promise<{ deleted: boolean }>
    },
    terminal(sessionId: string, signal?: AbortSignal): Promise<{
      id: string
      pid: number
      alive: boolean
      exit_code: number | null
      scrollback: string
    }> {
      const path = `/api/v1/terminals/${encodeURIComponent(sessionId)}`
      return readJson(path, signal) as Promise<{
        id: string
        pid: number
        alive: boolean
        exit_code: number | null
        scrollback: string
      }>
    },
  }
}
