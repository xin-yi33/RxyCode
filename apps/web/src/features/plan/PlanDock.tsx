export function PlanDock({
  plans,
  todos,
}: {
  plans: { id: string; title: string; status: string }[]
  todos: { id: string; title: string; status: string }[]
}) {
  return (
    <section data-plan>
      <h2>计划</h2>
      <ul>
        {plans.map((item) => (
          <li key={item.id} data-plan-id={item.id}>
            {item.title} {item.status}
          </li>
        ))}
      </ul>
      <ul>
        {todos.map((item) => (
          <li key={item.id} data-todo-id={item.id}>
            {item.title} {item.status}
          </li>
        ))}
      </ul>
    </section>
  )
}
