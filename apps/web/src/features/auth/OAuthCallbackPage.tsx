import { useEffect, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate, useSearchParams } from "react-router"

import { Button } from "../../components/ui/button"
import { createClient } from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { AuthLayout } from "./AuthLayout"

const api = createClient()

export function OAuthCallbackPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [error, setError] = useState("")

  useEffect(() => {
    const state = params.get("state") ?? ""
    const code = params.get("code") ?? ""
    if (!state || !code) {
      setError("授权回调缺少参数，请重新登录。")
      return
    }
    api
      .finishGithub(state, code)
      .then((body) => {
        queryClient.setQueryData(["me"], body)
        navigate("/app", { replace: true })
      })
      .catch((err: unknown) => setError(apiErrorText(err)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <AuthLayout>
      {error ? (
        <div role="alert">
          <p className="text-sm text-failure">{error}</p>
          <Button className="mt-4" variant="outline" onClick={() => navigate("/login")}>
            返回登录
          </Button>
        </div>
      ) : (
        <p role="status" className="text-sm text-muted">
          正在完成 GitHub 登录…
        </p>
      )}
      <p className="mt-4 text-center text-xs text-muted">
        <Link className="underline" to="/login">
          返回登录页
        </Link>
      </p>
    </AuthLayout>
  )
}
