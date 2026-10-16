import { useQuery } from "@tanstack/react-query"
import { useMemo } from "react"

import { createClient } from "../../sdk/client"

export function GitPanel(props: { projectId: string }) {
  const client = useMemo(() => createClient(), [])
  const tree = useQuery({
    queryKey: ["workspace-tree", props.projectId, ""],
    queryFn: () => client.workspaceTree(props.projectId, ""),
  })
  return (
    <section className="mt-4">
      <p>PR {tree.data?.pr_status ?? "none"}</p>
      <ul>
        {tree.data?.changes.map((file) => (
          <li key={file} data-git-file={file}>
            {file}
          </li>
        ))}
      </ul>
    </section>
  )
}
