// Streaming reveal: wrap ONLY the newly appended assistant prose in
// per-grapheme <span class="rxy-stream-glyph"> nodes so CSS can run a short
// staggered reveal. Everything before the reveal offset (history) stays plain,
// and code spans / link URLs are never split into animated glyphs.

export const REVEAL_STAGGER_MS = 30
// Cap the stagger so a very long chunk cannot schedule seconds of delay.
export const REVEAL_MAX_STEPS = 15
// On first mount of a live item, only the newest slice is animated.
export const REVEAL_MOUNT_MAX_GRAPHEMES = 240

type MdNode = {
  type: string
  value?: string
  data?: Record<string, unknown>
  children?: MdNode[]
  position?: { start?: { offset?: number } }
}

type MdTextNode = MdNode & {
  value: string
  data?: Record<string, unknown>
}

const segmenter =
  typeof Intl !== "undefined" && typeof Intl.Segmenter === "function"
    ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
    : null

/** Split by user-perceived characters (Intl.Segmenter, code points fallback). */
export function splitGraphemes(value: string): string[] {
  if (!value) return []
  if (!segmenter) return Array.from(value)
  const out: string[] = []
  for (const part of segmenter.segment(value)) out.push(part.segment)
  return out
}

// Combining marks / joiners / variation selectors that must not start a glyph.
const continuation = /[\p{M}\u200c\u200d\ufe0e\ufe0f]/u
const isLowSurrogate = (code: number) => code >= 0xdc00 && code <= 0xdfff

/**
 * Move a raw character offset forward to the next grapheme boundary so a
 * reveal split can never cut an emoji/CRLF/combining sequence in half.
 */
export function graphemeBoundaryAtOrAfter(text: string, offset: number): number {
  if (offset <= 0) return 0
  if (offset >= text.length) return text.length
  let index = Math.max(0, Math.floor(offset))
  while (index < text.length) {
    const code = text.charCodeAt(index)
    if (isLowSurrogate(code) || continuation.test(text[index])) {
      index += 1
      continue
    }
    break
  }
  return Math.min(index, text.length)
}

/** Start offset for the first live mount: animate at most the newest slice. */
export function mountRevealFrom(text: string): number {
  if (!text) return 0
  const graphemes = splitGraphemes(text)
  if (graphemes.length <= REVEAL_MOUNT_MAX_GRAPHEMES) return 0
  const tail = graphemes.slice(-REVEAL_MOUNT_MAX_GRAPHEMES).join("")
  return text.length - tail.length
}

// Source ranges that look like URLs/mail addresses: never reveal-animate them.
const URL_PATTERN =
  /(?:https?:\/\/|mailto:|www\.)[^\s<>()\[\]{}"'\u3000-\u303f\uff00-\uffef]+/gi

function urlRanges(text: string): Array<[number, number]> {
  const ranges: Array<[number, number]> = []
  URL_PATTERN.lastIndex = 0
  let match = URL_PATTERN.exec(text)
  while (match) {
    ranges.push([match.index, match.index + match[0].length])
    match = URL_PATTERN.exec(text)
  }
  return ranges
}

function overlapsUrl(ranges: Array<[number, number]>, start: number, end: number): boolean {
  for (const range of ranges) {
    if (start < range[1] && end > range[0]) return true
  }
  return false
}

export type StreamRevealOptions = {
  /** The markdown source being rendered. */
  text: string
  /** Character offset in `text` where the newly appended part begins. */
  from: number
}

/**
 * Remark plugin (transformer factory) that splits mdast text nodes at
 * `options.from` and wraps each new grapheme in a span. Text nodes cannot
 * exist inside code blocks/inline code in mdast, so code is naturally skipped;
 * URL-looking source ranges are additionally left plain.
 */
export function createStreamRevealPlugin(options: StreamRevealOptions) {
  return () => (tree: unknown) => {
    applyReveal(tree as MdNode, options)
  }
}

function applyReveal(root: MdNode, options: StreamRevealOptions): void {
  const { from: revealFrom, text } = options
  if (revealFrom >= text.length) return
  const ranges = urlRanges(text)
  let step = 0

  const walk = (parent: MdNode) => {
    const children = parent.children
    if (!children) return
    const next: MdNode[] = []
    for (const child of children) {
      const start = child.position?.start?.offset
      if (child.type === "text" && typeof child.value === "string" && typeof start === "number") {
        const textNode = child as MdTextNode
        const end = start + textNode.value.length
        if (end <= revealFrom || overlapsUrl(ranges, start, end)) {
          next.push(textNode)
          continue
        }
        const localFrom = Math.min(textNode.value.length, Math.max(0, revealFrom - start))
        const graphemes = splitGraphemes(textNode.value)
        let consumed = 0
        let splitIndex = 0
        while (splitIndex < graphemes.length && consumed < localFrom) {
          consumed += graphemes[splitIndex].length
          splitIndex += 1
        }
        if (splitIndex > 0) {
          next.push({ ...textNode, value: graphemes.slice(0, splitIndex).join("") })
        }
        for (let index = splitIndex; index < graphemes.length; index += 1) {
          const delay = Math.min(step, REVEAL_MAX_STEPS) * REVEAL_STAGGER_MS
          step += 1
          next.push({
            type: "text",
            value: graphemes[index],
            data: {
              hName: "span",
              hProperties: {
                className: ["rxy-stream-glyph"],
                style: { "--reveal-delay": delay + "ms" },
              },
            },
          })
        }
        continue
      }
      if (child.children) walk(child)
      next.push(child)
    }
    parent.children = next
  }

  walk(root)
}