import type { QuestionOption } from "../runs/eventReducer"

export type NumberedQuestionOption = {
  /** 1-based display position — exactly the payload order, never re-sorted. */
  index: number
  label: string
  value: string
  /** React key: index + value, so duplicate-ish rows still have stable keys. */
  key: string
}

function asText(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value)
}

/**
 * Numbered view of a question's options.
 *
 * Invariants:
 * - payload order is preserved verbatim (no sorting, no grouping by label);
 * - numbering is derived from that immutable order (1..N);
 * - rows with neither label nor value are not actionable and are dropped;
 * - exact (label, value) duplicates keep only their first position, so a
 *   replayed/echoed payload can never render (or submit) the same option twice;
 * - the value is kept byte-exact (the server validates answer ∈ option values).
 */
export function numberedQuestionOptions(
  options: readonly QuestionOption[] | null | undefined,
): NumberedQuestionOption[] {
  const seen = new Set<string>()
  const out: NumberedQuestionOption[] = []
  for (const option of options ?? []) {
    if (!option || typeof option !== "object") continue
    const label = asText(option.label)
    const value = asText(option.value)
    if (!label.trim() && !value.trim()) continue
    const dedupeKey = label + "\u0000" + value
    if (seen.has(dedupeKey)) continue
    seen.add(dedupeKey)
    const index = out.length + 1
    out.push({
      index,
      label: label.trim() ? label : value,
      value: value.trim() ? value : label,
      key: index + ":" + (value || label),
    })
  }
  return out
}

/**
 * Value -> human label for the folded "你的回答：…" line. Falls back to the
 * raw answer text (free-input answers) when no offered option matches.
 */
export function answerLabel(
  options: readonly QuestionOption[] | null | undefined,
  answer: string,
): string {
  const raw = asText(answer)
  if (!raw.trim()) return ""
  for (const option of options ?? []) {
    if (!option || typeof option !== "object") continue
    const label = asText(option.label)
    const value = asText(option.value)
    if (value === raw || label === raw || value.trim() === raw.trim()) {
      return label.trim() || value || raw
    }
  }
  return raw
}
