import { useQuery } from "@tanstack/react-query"

import { createClient } from "../../sdk/client"

const api = createClient()

function fmtSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

// W12: agent 写入会话工作区的文件清单（Notion/ChatGPT 式“本机文件”面）。
// 运行中每 10s 轮询——agent 可能还在往里写；空列表整块不渲染。
export function SessionFiles({
  sessionId,
  hasActive,
}: {
  sessionId: string
  hasActive: boolean
}) {
  const files = useQuery({
    queryKey: ["sessionFiles", sessionId],
    queryFn: ({ signal }) => api.listSessionFiles(sessionId, signal),
    refetchInterval: hasActive ? 10_000 : false,
    retry: false,
  })

  const items = files.data ?? []
  if (items.length === 0) return null

  return (
    <details className="rounded-lg border border-border bg-card px-3 py-2">
      <summary className="cursor-pointer text-xs font-medium text-muted">
        工作区文件（{items.length}）
      </summary>
      <ul className="mt-2 space-y-1">
        {items.map((file) => (
          <li key={file.path} className="flex items-center gap-2 text-xs">
            <a
              className="min-w-0 flex-1 truncate font-mono underline decoration-muted/50 underline-offset-2"
              href={api.sessionFileUrl(sessionId, file.path)}
              download={file.path.split("/").pop()}
            >
              {file.path}
            </a>
            <span className="shrink-0 text-muted">{fmtSize(file.size)}</span>
          </li>
        ))}
      </ul>
    </details>
  )
}
