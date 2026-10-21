import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { Button } from "../../components/ui/button"
import { Modal } from "../../components/ui/dialog"
import { createClient } from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { useUi } from "../../state/ui"

const api = createClient()

// 单设备冲突（409 DEVICE_IN_USE）的全局模态：任一 query/mutation 在
// queryClient.onError 里置位 ui.deviceConflict，这里弹层。选“在此设备
// 继续使用”走 POST /auth/device/claim，成功后全量失效查询并关闭；
// 失败就地显示错误，层不关。
export function DeviceConflictModal() {
  const deviceConflict = useUi((state) => state.deviceConflict)
  const setDeviceConflict = useUi((state) => state.setDeviceConflict)
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  if (!deviceConflict) return null

  const close = () => {
    if (busy) return
    setDeviceConflict(false)
  }

  const claim = () => {
    if (busy) return
    setBusy(true)
    setError("")
    api
      .claimDevice()
      .then(() => {
        setDeviceConflict(false)
        void queryClient.invalidateQueries()
      })
      .catch((err: unknown) => {
        setError(apiErrorText(err))
      })
      .finally(() => setBusy(false))
  }

  return (
    <Modal onClose={close} label="该账号正在另一台设备上使用" className="max-w-sm">
      <div className="p-5">
        <h3 className="text-base font-semibold">该账号正在另一台设备上使用</h3>
        <p className="mt-2 text-sm text-muted">
          同一账号同一时间只能在一台设备上使用。在此设备继续使用会中断另一台设备上的会话。
        </p>
        {error ? (
          <p role="alert" className="mt-3 text-xs text-failure">
            {error}
          </p>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={close} disabled={busy}>
            取消
          </Button>
          <Button size="sm" onClick={claim} disabled={busy}>
            {busy ? "切换中…" : "在此设备继续使用"}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
