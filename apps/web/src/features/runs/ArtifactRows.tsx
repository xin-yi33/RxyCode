import { useQuery } from "@tanstack/react-query"

import { IconArrowDown, IconEye } from "../../components/icons"
import { createClient, type ArtifactItem, type PreviewJob } from "../../sdk/client"
import { isActiveRunStatus } from "./status"

const api = createClient()

function formatBytes(size: number): string {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)}MB`
  if (size >= 1024) return `${Math.ceil(size / 1024)}KB`
  return `${size}B`
}

type ArtifactRowsProps = {
  runId: string
  status: string
  onPreview: (artifact: ArtifactItem) => void
}

// API-ART-01 manifest：终态前继续轮询，终态后定格（complete 的清单不再变）。
export function ArtifactRows({ runId, status, onPreview }: ArtifactRowsProps) {
  const manifest = useQuery({
    queryKey: ["artifacts", runId],
    queryFn: ({ signal }) => api.listArtifacts(runId, { signal }),
    refetchInterval: () => (isActiveRunStatus(status) ? 5_000 : false),
    retry: false,
  })
  const items = manifest.data?.artifacts ?? []
  if (!items.length) return null
  return (
    <ul data-artifacts className="mt-3 space-y-1.5">
      {items.map((item) => (
        <li
          key={item.artifact_id}
          className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm"
        >
          <span className="min-w-0 flex-1 truncate" title={item.relative_path || item.filename}>
            {item.filename || item.relative_path || item.artifact_id.slice(0, 8)}
          </span>
          {item.partial ? (
            <span className="rounded-full bg-waiting/15 px-1.5 py-0.5 text-xs text-waiting-ink">
              部分
            </span>
          ) : null}
          {item.availability !== "available" ? (
            <span className="rounded-full bg-border px-1.5 py-0.5 text-xs text-muted-ink">
              {item.availability === "pending" ? "生成中" : "不可用"}
            </span>
          ) : null}
          <span className="shrink-0 text-xs text-muted">{formatBytes(item.size)}</span>
          {item.preview_kind ? (
            <button
              type="button"
              aria-label={`预览 ${item.filename}`}
              className="rounded p-1 text-muted-ink hover:bg-sidebar"
              onClick={() => onPreview(item)}
            >
              <IconEye size={14} />
            </button>
          ) : null}
          <a
            href={item.download_url}
            download
            aria-label={`下载 ${item.filename}`}
            className="rounded p-1 text-muted-ink hover:bg-sidebar"
          >
            <IconArrowDown size={14} />
          </a>
        </li>
      ))}
      {manifest.data?.manifest_status === "partial" ? (
        <li className="px-1 text-xs text-muted">产物还在生成中…</li>
      ) : null}
    </ul>
  )
}

// ---- 预览（API-PREVIEW-01/02） ----------------------------------------------

export function usePreviewJob(previewId: string | null) {
  return useQuery({
    queryKey: ["preview", previewId],
    enabled: Boolean(previewId),
    queryFn: ({ signal }) => api.getPreview(previewId as string, signal),
    refetchInterval: (query) => {
      const job = query.state.data as PreviewJob | undefined
      return job && (job.status === "queued" || job.status === "running") ? 1_000 : false
    },
  })
}
