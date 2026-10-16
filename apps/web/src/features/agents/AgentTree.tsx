export function AgentTree({
  nodes,
  finalText,
}: {
  nodes: Array<{
    id: string
    parent_id: string
    role: string
    status: string
  }>
  finalText: string
}) {
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
      <p data-final={finalText}>{finalText}</p>
      <button type="button">steer</button>
      <button type="button">cancel</button>
    </section>
  )
}
