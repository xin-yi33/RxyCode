import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useMemo } from "react"

import { createClient } from "../../sdk/client"

export function useLocalLogin() {
  const client = useMemo(() => createClient(), [])
  const queries = useQueryClient()
  return useMutation({
    mutationFn: (secret: string) => client.localLogin(secret),
    onSuccess: async () => {
      await queries.invalidateQueries({ queryKey: ["me"] })
    },
  })
}
