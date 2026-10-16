import { useQuery } from "@tanstack/react-query"

import { createClient } from "../../sdk/client"

export function ArtifactPanel({ runId }: { runId: string }) {
  const client = createClient()
  const query = useQuery({
    queryKey: ["artifacts", runId],
    queryFn: () => client.listArtifacts(runId),
  })
  return (
    <section data-artifacts>
      <h2>产物</h2>
      <ul>
        {query.data?.artifacts.map((item) => (
          <li key={item.artifact_id}>
            <a href={`/api/v1/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(item.artifact_id)}`}>
              {item.artifact_id}
            </a>
          </li>
        ))}
      </ul>
    </section>
  )
}
