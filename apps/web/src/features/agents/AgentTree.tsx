export function AgentTree({
  agents,
  nodes,
  finalText,
}: {
  agents?: { id: string; name: string; status: string; cost: string }[]
  nodes?: Array<{
    id: string
    parent_id: string
    role: string
    status: string
  }>
  finalText?: string
}) {
  if (nodes && nodes.length > 0) {
    return (
      <section aria-label="agent-tree">
        {nodes.map((node) => (
          <article
            key={node.id}
            data-id={node.id}
            data-parent={node.parent_id}
            data-status={node.status}
            data-role={node.role}
          >
            {node.role}
          </article>
        ))}
        <p data-final={finalText ?? ""}>{finalText ?? ""}</p>
        <button type="button">steer</button>
        <button type="button">cancel</button>
      </section>
    )
  }
  const rows = agents ?? []
  return (
    <section data-agents>
      <h2>子代理</h2>
      <ul>
        {rows.map((item) => (
          <li key={item.id} data-agent-id={item.id} data-agent-status={item.status}>
            {item.name} {item.cost}
          </li>
        ))}
      </ul>
    </section>
  )
}
