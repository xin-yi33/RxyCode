import { DiffEditor } from "@monaco-editor/react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useMemo, useState } from "react"

import { ApiError, createClient } from "../../sdk/client"

export function DiffReview(props: { projectId: string; path: string }) {
  const client = useMemo(() => createClient(), [])
  const queries = useQueryClient()
  const [conflict, setConflict] = useState(false)
  const diff = useQuery({
    queryKey: ["workspace-diff", props.projectId, props.path],
    queryFn: () => client.workspaceDiff(props.projectId, props.path),
    enabled: props.path.length > 0,
    retry: false,
  })
  const submit = async (hunkId: string, decision: "accept" | "reject") => {
    if (!diff.data) return
    try {
      await client.reviewHunk(props.projectId, {
        path: props.path,
        hunk_id: hunkId,
        decision,
        base_revision: diff.data.base_revision,
      })
      setConflict(false)
      await queries.invalidateQueries({
        queryKey: ["workspace-diff", props.projectId, props.path],
      })
    } catch (error) {
      if (error instanceof ApiError && (error.status === 409 || error.code === "CONFLICT")) {
        setConflict(true)
      }
    }
  }
  if (!props.path) return null
  if (diff.isError) {
    const denied = diff.error instanceof ApiError && diff.error.status === 403
    return <p role="alert">{denied ? "拒绝" : "无法读取"}</p>
  }
  if (!diff.data) return <p>正在加载</p>
  return (
    <section className="mt-4" data-base-revision={diff.data.base_revision}>
      <DiffEditor
        original={diff.data.before}
        modified={diff.data.after}
        language="plaintext"
        height="240px"
        options={{ readOnly: true, renderSideBySide: true }}
      />
      {diff.data.hunks.map((hunk) => (
        <article key={hunk.id} className="mt-3">
          <p>{hunk.header}</p>
          {hunk.lines.map((line, index) => (
            <p key={`${hunk.id}-${index}`} data-hunk-line>
              {line}
            </p>
          ))}
          <button type="button" onClick={() => void submit(hunk.id, "accept")}>
            接受
          </button>
          <button type="button" onClick={() => void submit(hunk.id, "reject")}>
            拒绝
          </button>
        </article>
      ))}
      {conflict ? <p role="alert">刷新</p> : null}
    </section>
  )
}
