// SPA 导航出口：React 树之外（query cache 回调、EventSource 恢复）也需要
// 用 router.navigate 而不是 location.assign —— 整页刷新会丢掉内存里的
// Zustand 草稿（PRD §3.3：草稿按身份保留在内存分区）。
// App.tsx 在创建 router 后调用 registerNavigate 注入。

let handler: ((to: string, opts?: { replace?: boolean }) => void) | null = null

export function registerNavigate(
  fn: (to: string, opts?: { replace?: boolean }) => void,
): void {
  handler = fn
}

export function appNavigate(to: string, opts?: { replace?: boolean }): void {
  if (handler) {
    try {
      handler(to, opts)
      return
    } catch {
      // fall through to the hard redirect
    }
  }
  window.location.assign(to)
}
