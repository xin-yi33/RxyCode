import { useQuery } from "@tanstack/react-query"

import { Button } from "../../components/ui/button"
import { Modal } from "../../components/ui/dialog"
import { createClient } from "../../sdk/client"

const api = createClient()

// “关于”对话框：产品名 + 后端构建戳（GET /api/v1/version 免登录），
// 挂载即拉取一次，失败就地降级为 unknown。
export function AboutDialog({ onClose }: { onClose: () => void }) {
  const version = useQuery({
    queryKey: ["buildStamp"],
    queryFn: ({ signal }) => api.getVersion(signal),
    staleTime: 300_000,
  })

  return (
    <Modal onClose={onClose} label="关于 RxyCode" className="max-w-sm">
      <div className="p-5">
        <h3 className="text-base font-semibold">RxyCode Web</h3>
        <p className="mt-2 text-sm text-muted">
          AI 全栈编程助手 —— 任务在隔离沙箱中执行，支持自有模型接入（BYOK）。
        </p>
        <dl className="mt-4 space-y-1 text-sm text-muted">
          <div className="flex gap-2">
            <dt className="w-20 shrink-0">构建版本</dt>
            <dd className="font-mono">
              {version.isPending
                ? "…"
                : version.isError
                  ? "unknown"
                  : version.data.commit}
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-20 shrink-0">构建时间</dt>
            <dd className="font-mono">
              {version.isPending
                ? "…"
                : version.isError
                  ? "unknown"
                  : version.data.built_at}
            </dd>
          </div>
        </dl>
        <div className="mt-5 flex justify-end">
          <Button variant="outline" size="sm" onClick={onClose}>
            关闭
          </Button>
        </div>
      </div>
    </Modal>
  )
}
