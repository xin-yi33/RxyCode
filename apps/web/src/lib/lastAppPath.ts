// SET-01：「返回应用」回到进入设置前的最后一个站内应用位置。
// 模块级变量由 ConsoleShell 的 location effect 维护；/settings 本身不算
// 应用位置。刷新后内存丢失则回退 /app —— 诚实的回退，不编造历史。
let last = "/app"

export function recordAppPath(pathname: string, search: string) {
  if (!pathname.startsWith("/settings")) {
    last = pathname + search
  }
}

export function lastAppPath(): string {
  return last
}
