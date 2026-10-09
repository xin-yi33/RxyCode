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

// 2026-10-09 Todo 清单展示规则（仅渲染层，数据层不变，用户规格 §一–§五）：
// §一 符号映射：pending [ ] / in_progress [.] / completed [√] / cancelled [x] / blocked [!]
// §二 不消失规则：存在任一未终结任务（pending/in_progress/blocked）时，
//   所有 pending/in_progress/completed 条目必须逐条显示，禁止折叠成计数摘要；
//   cancelled 可逐条（此处选逐条 [x]）；汇总计数行 (n completed) 只能补充。
// §三 清表时机：只有全部条目终结（completed/cancelled）后清单才允许收起。
const OPEN = new Set(["pending", "in_progress", "blocked"]);

export function todoMark(status: string): string {
  if (status === "completed") return "[√]";
  // 2026-10-09 用户裁定：进行中用正中间的中点「·」(U+00B7)，不是基线点
  // 「.」也不是项目符号「•」。
  if (status === "in_progress") return "[·]";
  if (status === "blocked") return "[!]";
  if (status === "cancelled") return "[x]";
  return "[ ]";
}

export function todoDockLines(snapshot: TodoDockSnapshot | null | undefined): string[] {
  const items = snapshot?.items ?? [];
  const hasOpen = items.some((item) => OPEN.has(String(item.status)));
  // §三：全部终结才允许收起（无未终结任务 → dock 不占行）。
  if (!hasOpen) return [];
  // §二：有未终结任务时，pending/in_progress/completed 全部逐条显示（含 id 对齐判例形态）。
  const lines = items.map(
    (item) => `${todoMark(item.status)} ${item.id}: ${item.content}`,
  );
  const done = items.filter((item) => item.status === "completed").length;
  const dropped = items.filter((item) => item.status === "cancelled").length;
  if (done || dropped) {
    const parts = [
      done ? `${done} completed` : "",
      dropped ? `${dropped} cancelled` : "",
    ].filter(Boolean);
    // 汇总行仅作补充，绝不取代上面受保护的逐条条目。
    lines.push(`(${parts.join(", ")})`);
  }
  return lines;
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
