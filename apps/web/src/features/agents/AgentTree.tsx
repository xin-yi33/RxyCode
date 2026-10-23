export function AgentTree({
  agents,
  nodes,
  finalText,
  steerText,
  onSteerText,
  onSteer,
  onCancel,
}: {
  agents?: { id: string; name: string; status: string; cost: string }[]
  nodes?: Array<{
    id: string
    parent_id: string
    role: string
    status: string
    tokens?: number
  }>
  finalText?: string
  steerText?: string
  onSteerText?: (text: string) => void
  onSteer?: (text: string) => void
  onCancel?: (id: string) => void
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
            data-tokens={node.tokens ?? 0}
          >
            {node.role}
            <button type="button" onClick={() => onCancel?.(node.id)}>
              cancel
            </button>
          </article>
        ))}
        <p data-final={finalText ?? ""}>{finalText ?? ""}</p>
        <input
          aria-label="steer-text"
          value={steerText ?? ""}
          onChange={(event) => onSteerText?.(event.target.value)}
        />
        <button
          type="button"
          onClick={() => {
            const text = (steerText ?? "").trim()
            if (text) onSteer?.(text)
          }}
        >
          steer
        </button>
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
