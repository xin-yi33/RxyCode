/** Zero-LLM follow-up recommendations from B12-like event text. */

const HINTS: Array<{ re: RegExp; task: string }> = [
  { re: /todo|next step/i, task: 'Continue the remaining todos' },
  { re: /test fail|failing test/i, task: 'Fix failing tests' },
  { re: /lint|typecheck/i, task: 'Fix lint or typecheck errors' },
  { re: /review|diff/i, task: 'Open review for the latest diff' }
]

export function scanFollowups(events: readonly { text: string }[]): string[] {
  const out: string[] = []
  for (const event of events) {
    for (const hint of HINTS) {
      if (hint.re.test(event.text) && !out.includes(hint.task)) out.push(hint.task)
    }
  }
  return out.slice(0, 3)
}
