import { Composer } from "./Composer"

// /app — new-task landing. The composer posts /tasks which creates the
// session, then navigates to /app/s/<id>.
export function NewSessionPage() {
  return (
    <div className="mx-auto flex min-h-full max-w-3xl flex-col justify-end px-4 pb-8 pt-16">
      <h2 className="pb-6 text-center text-2xl font-semibold tracking-tight">
        有什么可以帮你的？
      </h2>
      <div className="-mx-4">
        <Composer sessionId={null} />
      </div>
    </div>
  )
}
