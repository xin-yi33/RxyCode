import { Composer } from "./Composer"

// /app — 空态：标题 + 输入框作为一组整体垂直居中。提交 POST /tasks
// 创建会话后跳到 /app/s/<id>。
export function NewSessionPage() {
  return (
    <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-4 pb-16">
      <h2 className="pb-6 text-center text-2xl font-semibold tracking-tight">
        今天要做什么？
      </h2>
      <div className="-mx-4">
        <Composer sessionId={null} />
      </div>
    </div>
  )
}
