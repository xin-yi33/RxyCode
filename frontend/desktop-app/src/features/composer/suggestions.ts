export function suggestionsFromGitLog(lines: readonly string[]): string[] {
  return lines
    .map((line) => line.replace(/^[a-f0-9]+\s+/i, '').trim())
    .filter((line) => line.length > 0)
    .slice(0, 3)
}

export function suggestionsFromRecentMessages(messages: readonly string[]): string[] {
  const last = messages.slice(-2).join(' ')
  if (last.trim() === '') return []
  const word = last.split(/\s+/).find((item) => item.length > 3) ?? 'this'
  return [`Continue ${word}`, `Explain ${word}`]
}

export function suggestionsVisible(userMessageCount: number, gitOk: boolean): boolean {
  if (userMessageCount >= 5) return false
  return gitOk || userMessageCount > 0
}

export function applySuggestionKey(key: string): 'accept' | 'dismiss' | 'send' | null {
  if (key === 'Tab') return 'accept'
  if (key === 'Escape') return 'dismiss'
  if (key === 'Enter') return 'send'
  return null
}
