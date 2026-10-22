import type { ReactNode } from "react"
import { useMobileViewport } from "../../lib/useMobileViewport"

export function AuthLayout({ children }: { children: ReactNode }) {
  useMobileViewport()
  return (
    <main className="rxy-auth-layout flex min-h-screen items-center justify-center bg-sidebar px-4 py-8 text-foreground">
      <section className="w-full max-w-[400px] rounded-xl border border-border bg-card p-6 sm:p-8">
        <h1 className="text-center text-xl font-semibold tracking-tight">RxyCode</h1>
        <div className="mt-6">{children}</div>
      </section>
    </main>
  )
}
