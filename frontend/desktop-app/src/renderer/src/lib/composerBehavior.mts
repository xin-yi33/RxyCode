export function canSubmitComposer(input: {
  disabled: boolean
  running: boolean
  text: string
  hasAttachment?: boolean
  modelReady?: boolean
}): boolean {
  return (
    !input.disabled &&
    input.modelReady !== false &&
    (input.text.trim() !== '' || input.hasAttachment === true)
  )
}

export function promptWithAttachment(
  text: string,
  attachment: { name: string; path: string } | null
): string {
  const trimmed = text.trim()
  if (attachment === null) return trimmed
  const hint = `请先读取附件：${attachment.path}`
  return trimmed === '' ? hint : `${trimmed}\n\n${hint}`
}

export function shouldSubmitOnKey(input: {
  key: string
  shiftKey: boolean
  running: boolean
}): boolean {
  return input.key === 'Enter' && !input.shiftKey
}
