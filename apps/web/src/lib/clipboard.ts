// Shared clipboard helper for the web UI.
//
// One place decides whether a copy really happened: the async Clipboard API
// first, then the legacy execCommand fallback (whose boolean result is checked
// — no fake success). Callers must never show "copied" without true.

export async function copyText(text: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      return false
    }
  }
  if (typeof document === "undefined") return false
  const area = document.createElement("textarea")
  area.value = text
  area.setAttribute("readonly", "")
  area.style.position = "fixed"
  area.style.opacity = "0"
  area.style.pointerEvents = "none"
  document.body.appendChild(area)
  try {
    area.select()
    return document.execCommand("copy") === true
  } catch {
    return false
  } finally {
    document.body.removeChild(area)
  }
}
