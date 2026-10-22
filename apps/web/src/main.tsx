import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import { App } from "./app/App"
import "./styles/globals.css"
import { isAuthTransportAllowed, publicHttpsUpgradeUrl } from "./features/auth/authTransport"

const root = document.getElementById("root")
if (!root) {
  throw new Error("root missing")
}

const httpsUpgrade = publicHttpsUpgradeUrl(window.location)
if (httpsUpgrade) {
  // Preserve route/query/hash, but never carry URL username/password onto the
  // secure origin. This runs before React can render a credential form.
  window.location.replace(httpsUpgrade)
} else if (!isAuthTransportAllowed(window.location)) {
  createRoot(root).render(
    <main role="alert" className="mx-auto max-w-xl space-y-3 p-6 text-center">
      <h1 className="text-lg font-semibold">连接不安全</h1>
      <p className="text-sm text-muted">
        登录、验证码和其他凭据不会通过非安全 HTTP 页面发送。请使用 HTTPS 安全入口；本机开发可使用 localhost。
      </p>
      <a className="text-sm underline" href="https://rxycode.xyz">
        打开 RxyCode 安全入口
      </a>
    </main>,
  )
} else {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}
