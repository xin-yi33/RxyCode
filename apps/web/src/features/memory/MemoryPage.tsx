import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { useParams } from "react-router"

export type MemoryNote = {
  id: string
  body: string
  project_id: string
}

function escapeText(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
}

export function memoryMarkup(notes: MemoryNote[]): string {
  const items = notes
    .map((note) => `<li data-memory-id="${escapeText(note.id)}">${escapeText(note.body)}</li>`)
    .join("")
  return `<section data-memory>${items}</section>`
}

async function csrfToken(): Promise<string> {
  const response = await fetch("/api/v1/auth/csrf", { credentials: "same-origin" })
  const payload = (await response.json()) as { csrf_token?: string }
  return payload.csrf_token ?? ""
}

async function send(path: string, method: string, body?: unknown): Promise<void> {
  await fetch(path, {
    method,
    credentials: "same-origin",
    headers: {
      "content-type": "application/json",
      "x-csrf-token": await csrfToken(),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

async function loadMemory(projectId: string): Promise<MemoryNote[]> {
  const response = await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/memory`, {
    credentials: "same-origin",
  })
  const payload = (await response.json()) as { memories?: MemoryNote[] }
  return payload.memories ?? []
}

export function MemoryPage() {
  const { projectId = "" } = useParams()
  const [draft, setDraft] = useState("")
  const query = useQuery({
    queryKey: ["memory", projectId],
    queryFn: () => loadMemory(projectId),
  })
  const refresh = () => query.refetch()
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-4 py-6">
      <h1>记忆</h1>
      <form
        className="mt-3 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          void send(`/api/v1/projects/${encodeURIComponent(projectId)}/memory`, "POST", { body: draft }).then(refresh)
        }}
      >
        <input aria-label="memory-body" value={draft} onChange={(event) => setDraft(event.target.value)} />
        <button type="submit">保存</button>
      </form>
      <ul data-memory>
        {(query.data ?? []).map((note) => (
          <li key={note.id} data-memory-id={note.id}>
            {note.body}
            <button
              type="button"
              onClick={() =>
                void send(`/api/v1/projects/${encodeURIComponent(projectId)}/memory`, "POST", {
                  id: note.id,
                  body: draft,
                }).then(refresh)
              }
            >
              修改
            </button>
            <button
              type="button"
              onClick={() =>
                void send(
                  `/api/v1/projects/${encodeURIComponent(projectId)}/memory/${encodeURIComponent(note.id)}`,
                  "DELETE",
                ).then(refresh)
              }
            >
              删除
            </button>
          </li>
        ))}
      </ul>
    </main>
  )
}
