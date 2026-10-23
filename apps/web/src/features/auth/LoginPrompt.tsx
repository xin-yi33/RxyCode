// 动作级登录拦截（PRD §3.2/E2E-01）：访客触发需要身份的动作时弹出的
// 模态提示。点“去登录”时先置 pendingIntent —— 登录返回后 Composer
// 显示“草稿已保留，确认后发送”横幅，绝不自动提交（不自动付费）。
import { useLocation, useNavigate } from "react-router"

import { loginPathFor } from "../../app/AuthGate"
import { Button } from "../../components/ui/button"
import { Modal } from "../../components/ui/dialog"
import { useUi } from "../../state/ui"

export function LoginPrompt({
  title = "发送任务需要登录",
  description = "登录后即可继续，当前输入内容会保留。",
  onClose,
}: {
  title?: string
  description?: string
  onClose: () => void
}) {
  const navigate = useNavigate()
  const location = useLocation()
  const setPendingIntent = useUi((state) => state.setPendingIntent)

  const goLogin = () => {
    setPendingIntent(true)
    onClose()
    // SPA 跳转：内存里的草稿随路由保留，不用 location.assign 整页刷新。
    navigate(loginPathFor(location.pathname, location.search))
  }

  return (
    <Modal onClose={onClose} label={title} className="max-w-sm">
      <div className="p-5">
        <h3 className="text-base font-semibold">{title}</h3>
        <p className="mt-2 text-sm text-muted">{description}</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button size="sm" onClick={goLogin}>
            去登录
          </Button>
        </div>
      </div>
    </Modal>
  )
}
