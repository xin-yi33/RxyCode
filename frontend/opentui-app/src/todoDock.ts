/** Read-only OpenTUI view of one TodoSnapshot. Not a second store. */

export interface TodoDockItem {
  id: string;
  content: string;
  status: string;
}

export interface TodoDockSnapshot {
  list_id: string;
  revision: number;
  items: TodoDockItem[];
}

export interface TodoUpdatedEvent {
  event_id?: string;
  seq?: number;
  timestamp?: string;
  snapshot?: TodoDockSnapshot;
}

const OPEN = new Set(["pending", "in_progress", "blocked"]);

export function todoMark(status: string): string {
  if (status === "completed") return "[✓]";
  if (status === "in_progress") return "[•]";
  if (status === "blocked") return "[!]";
  if (status === "cancelled") return "[-]";
  return "[ ]";
}

export function todoDockLines(snapshot: TodoDockSnapshot | null | undefined): string[] {
  const items = snapshot?.items ?? [];
  const open = items.filter((item) => OPEN.has(String(item.status)));
  if (open.length === 0) return [];
  return open.map((item) => `${todoMark(item.status)} ${item.content}`);
}

export function applyTodoUpdated(
  current: TodoDockSnapshot,
  event: TodoUpdatedEvent,
): TodoDockSnapshot {
  const next = event.snapshot;
  if (!next || !Array.isArray(next.items)) return current;
  if (Number(next.revision) < Number(current.revision)) return current;
  return {
    list_id: String(next.list_id || current.list_id || "default"),
    revision: Number(next.revision) || current.revision,
    items: next.items.map((item) => ({
      id: String(item.id),
      content: String(item.content || ""),
      status: String(item.status || "pending"),
    })),
  };
}

export function snapshotFromTodoGet(payload: unknown): TodoDockSnapshot {
  const body = (payload ?? {}) as Partial<TodoDockSnapshot>;
  return applyTodoUpdated(
    { list_id: "default", revision: 0, items: [] },
    { snapshot: body as TodoDockSnapshot },
  );
}

export function keyAction(key: { ctrl?: boolean; name?: string }): "todo" | "thinking" | null {
  if (!key.ctrl) return null;
  const name = String(key.name || "").toLowerCase();
  if (name === "t") return "todo";
  if (name === "e") return "thinking";
  return null;
}
