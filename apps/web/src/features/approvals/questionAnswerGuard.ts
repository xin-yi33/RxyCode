// Exactly-one-answer guard, shared by every QuestionItem the page mounts.
//
// question.requested can reach the browser more than once (follow=0 replay +
// SSE snapshot, a duplicated timeline row, two question cards for the same
// question id) and a user can double-click/tap faster than React re-renders.
// A per-instance ref is not enough for those cases, so the claim lives at
// module scope: the first submit wins, every later attempt is a no-op.
//
// A claim is kept after a successful POST (a question can be answered exactly
// once — a second POST would only 409) and released on a retryable failure so
// the user can retry.
const inFlight = new Set<string>()
const answered = new Set<string>()

/** Claim a question for one submission. Returns false when already claimed. */
export function beginQuestionAnswer(questionId: string): boolean {
  if (!questionId || inFlight.has(questionId) || answered.has(questionId)) {
    return false
  }
  inFlight.add(questionId)
  return true
}

/** Release the in-flight claim; `keepAnswered` keeps the question closed. */
export function finishQuestionAnswer(questionId: string, keepAnswered: boolean): void {
  inFlight.delete(questionId)
  if (keepAnswered && questionId) answered.add(questionId)
}

export function isQuestionAnswered(questionId: string): boolean {
  return answered.has(questionId)
}

/** Test-only reset (bun-driven unit tests); production code never calls it. */
export function __resetQuestionAnswerGuard(): void {
  inFlight.clear()
  answered.clear()
}
