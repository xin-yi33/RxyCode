export function AgentTree({
  agents,
}: {
  agents: { id: string; name: string; status: string; cost: string }[]
}) {
  return (
    <section data-agents>
      <h2>子代理</h2>
      <ul>
        {agents.map((item) => (
          <li key={item.id} data-agent-id={item.id} data-agent-status={item.status}>
            {item.name} {item.cost}
          </li>
        ))}
      </ul>
    </section>
  )
}
