export type Me = { user_id: string; tenant_id: string }

export type Project = { id: string; name: string }

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string) {
    super(code)
    this.name = "ApiError"
    this.status = status
    this.code = code
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
    try {
      const body = (await response.json()) as { code?: string }
      if (body.code) code = body.code
    } catch {
      code = "UNAVAILABLE"
    }
    throw new ApiError(response.status, code)
  }
  return response.json()
}

async function writeJson(
  path: string,
  body: unknown,
  extra: Record<string, string> = {},
): Promise<unknown> {
  const csrf = (await readJson("/api/v1/auth/csrf")) as { csrf_token: string }
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
      "x-csrf-token": csrf.csrf_token,
      ...extra,
    },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    let code = "UNAVAILABLE"
    try {
      const payload = (await response.json()) as { code?: string }
      if (payload.code) code = payload.code
    } catch {
      code = "UNAVAILABLE"
    }
    throw new ApiError(response.status, code)
  }
  return response.json()
}

export type SessionInfo = { id: string; title: string; project_id: string }

export function createClient() {
  return {
    getMe(signal?: AbortSignal): Promise<Me> {
      return readJson("/api/v1/me", signal) as Promise<Me>
    },
    localLogin(secret: string): Promise<Me> {
      return writeJson("/api/v1/auth/local/login", {}, {
        "x-local-secret": secret,
      }) as Promise<Me>
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
    openRunEvents(runId: string): EventSource {
      return new EventSource(`/api/v1/runs/${encodeURIComponent(runId)}/events`)
    },
  }
}
