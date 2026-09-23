/** Grok Build plan-approval actions (github.com/xai-org/grok-build user-guide/19-plan-mode.md). */

export type PlanAction = "approve" | "request_changes" | "comment" | "copy" | "quit";

export type PlanComposerIntent =
  | { kind: "approve" }
  | { kind: "request_changes" }
  | { kind: "comment" }
  | { kind: "copy" }
  | { kind: "quit" }
  | { kind: "start_build" }
  | { kind: "revise" };

/** Highlighted shortcut keys on the plan action bar. */
export const PLAN_ACTIONS: Array<{ key: string; id: PlanAction; label: string }> = [
  { key: "a", id: "approve", label: "approve" },
  { key: "s", id: "request_changes", label: "request changes" },
  { key: "c", id: "comment", label: "comment" },
  { key: "y", id: "copy", label: "copy plan" },
  { key: "q", id: "quit", label: "quit plan" },
];

const START_BUILD_RE =
  /^(开始吧|开始|开工|动手|执行|实施|按计划(执行|开始|做)?|go|start|implement( it)?( now)?|do it|lgtm)$/i;

export function isPlanShortcutKey(name: string | undefined): PlanAction | null {
  const key = String(name || "").toLowerCase();
  const hit = PLAN_ACTIONS.find((row) => row.key === key);
  return hit ? hit.id : null;
}

export function classifyPlanComposer(text: string): PlanComposerIntent {
  const trimmed = text.replace(/\s+/g, " ").trim();
  if (!trimmed) return { kind: "revise" };
  const lower = trimmed.toLowerCase();
  if (lower === "a" || lower === "approve") return { kind: "approve" };
  if (lower === "s") return { kind: "request_changes" };
  if (lower === "c") return { kind: "comment" };
  if (lower === "y") return { kind: "copy" };
  if (lower === "q") return { kind: "quit" };
  if (START_BUILD_RE.test(trimmed)) return { kind: "start_build" };
  return { kind: "revise" };
}

export function implementPlanPrompt(planBody: string): string {
  return [
    "按已批准的计划开始实施，不要重新规划，不要继续会话里的旧项目。",
    "",
    planBody.trim(),
  ].join("\n");
}

export function requestChangesPrompt(planBody: string, userNotes?: string): string {
  const notes = (userNotes || "").replace(/\s+/g, " ").trim();
  const isBareShortcut = !notes || notes.toLowerCase() === "s" || notes.toLowerCase() === "request changes";
  if (isBareShortcut) {
    return `请修订这份计划，输出更新后的完整 Markdown 计划文档。\n\n${planBody.trim()}`;
  }
  return `请按以下要求修订计划，输出更新后的完整 Markdown 计划文档。\n\n${notes}\n\n---\n当前计划：\n\n${planBody.trim()}`;
}

export function revisePlanPrompt(userText: string, planBody: string): string {
  return [
    userText.trim(),
    "",
    "---",
    "当前待审计划附后。请自行判断这句话：明确改计划则输出更新后的完整 Markdown 计划；催开工则不要改计划，提醒用户按 a / approve 或切到 Build；其余正常回答并说明有没有改计划。",
    "",
    planBody.trim(),
  ].join("\n");
}

export function commentPlanPrompt(userText: string, lineNo: number, lineText: string): string {
  const note = userText.trim() || "请按这条批注修订计划。";
  return `对计划第 ${lineNo} 行的批注：${note}\n> ${lineText}`;
}

export function planLineColor(line: string): "heading" | "list" | "code" | "quote" | "hr" | "text" {
  if (/^#{1,6}\s+\S/.test(line)) return "heading";
  if (/^\s*```/.test(line) || /^\s{4}\S/.test(line)) return "code";
  if (/^\s*([-*+]|\d+\.)\s/.test(line)) return "list";
  if (/^>\s?/.test(line)) return "quote";
  if (/^(\s*[-*_]){3,}\s*$/.test(line)) return "hr";
  return "text";
}
