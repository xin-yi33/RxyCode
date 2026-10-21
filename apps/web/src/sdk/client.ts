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

export type Project = { id: string; name: string }

export type RunAccepted = {
  run_id: string
  status: string
  session_id: string
  events_url: string
}

export type RunSummary = {
  run_id: string
  status: string
  created_at: string | null
  message: string
  permission_profile: string
  final_preview: string
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
}

export type SessionListItem = {
  id: string
  title: string
  project_id: string
  updated_at: string | null
  last_run: { run_id: string; status: string } | null
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
): Promise<unknown> {
  let token = await fetchCsrfToken()
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const response = await fetch(path, {
      method: "POST",
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

export function createClient() {
  return {
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
      return writeJson("/api/v1/projects", { name, repo_config: repoConfig }) as Promise<Project>
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
    }): Promise<RunAccepted> {
      return writeJson("/api/v1/tasks", body) as Promise<RunAccepted>
    },
    createRun(
      sessionId: string,
      body: {
        message: string
        request_id: string
        permission_profile: "confirm" | "full"
      },
    ): Promise<RunAccepted> {
      const path = `/api/v1/sessions/${encodeURIComponent(sessionId)}/runs`
      return writeJson(path, body) as Promise<RunAccepted>
    },
    listSessions(signal?: AbortSignal): Promise<SessionListItem[]> {
      return readJson("/api/v1/sessions", signal).then((body) => {
        const record = body as { sessions?: SessionListItem[] }
        return record.sessions ?? []
      })
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
