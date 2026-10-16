import { useQuery } from "@tanstack/react-query"
import { useParams } from "react-router"
import { useState } from "react"

export type MemoryNote = {
  id: string
  body: string
  project_id: string
}

export function memoryMarkup(notes: MemoryNote[]): string {
  const items = notes
    .map((note) => `<li data-memory-id="${note.id}" data-project="${note.project_id}">${note.body}</li>`)
    .join("")
  return `<section data-memory>${items}</section>`
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
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-4 py-6">
      <h1>记忆</h1>
      <form
        className="mt-3 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          void fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/memory`, {
            method: "POST",
            credentials: "same-origin",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ body: draft }),
          })
        }}
      >
        <input aria-label="memory-body" value={draft} onChange={(event) => setDraft(event.target.value)} />
        <button type="submit">保存</button>
      </form>
      <div dangerouslySetInnerHTML={{ __html: memoryMarkup(query.data ?? []) }} />
    </main>
  )
}
