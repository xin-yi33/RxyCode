import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react"

// Single chat scroll controller (task-6 UI-04). The SessionPage owns exactly one
// scroll container; this hook is the only place that writes its scrollTop.
//
// Contract:
// * follow only while distanceToBottom <= 40;
// * jump-to-latest appears when distanceToBottom > 120;
// * a user scroll-up pauses immediately, a programmatic scroll never pauses;
// * history prepends / image loads / collapse toggles all share the same state.
export const FOLLOW_DISTANCE = 40
export const JUMP_DISTANCE = 120
// Browser scrollTop can round; ignore sub-pixel/rounding differences.
const PROGRAMMATIC_TOLERANCE = 2
// A recent content-driven layout may shift scrollTop without user input
// (scroll anchoring when older runs are prepended). Defer to the observer then.
const CONTENT_SYNC_GRACE_MS = 500

export function distanceToBottom(el: HTMLElement): number {
  return Math.max(0, el.scrollHeight - el.clientHeight - el.scrollTop)
}

export type ScrollAnchor = { scrollTop: number; scrollHeight: number }

export type ChatScrollController = {
  scrollRef: RefObject<HTMLDivElement | null>
  contentRef: RefObject<HTMLDivElement | null>
  showJumpToLatest: boolean
  isFollowing: () => boolean
  scrollToLatest: () => void
  captureAnchor: () => ScrollAnchor | null
  restoreAnchor: (anchor: ScrollAnchor) => void
}

function findNestedScroller(
  target: EventTarget | null,
  boundary: HTMLElement | null,
): HTMLElement | null {
  if (!boundary || !(target instanceof Element)) return null
  let node: Element | null = target
  while (node && node !== boundary) {
    if (node instanceof HTMLElement) {
      const overflowY = getComputedStyle(node).overflowY
      if (
        (overflowY === "auto" || overflowY === "scroll") &&
        node.scrollHeight > node.clientHeight + 1
      ) {
        return node
      }
    }
    node = node.parentElement
  }
  return null
}

export function useChatScrollController(sessionKey: string): ChatScrollController {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const contentRef = useRef<HTMLDivElement | null>(null)
  const [showJumpToLatest, setShowJumpToLatest] = useState(false)

  const followingRef = useRef(true)
  const expectedTopRef = useRef<number | null>(null)
  const expectedTimerRef = useRef<number | null>(null)
  const lastScrollTopRef = useRef(0)
  const lastContentSyncRef = useRef(0)
  // 最近一次真实用户输入（滚轮/触摸/翻页键）的时间戳。浏览器 scroll
  // anchoring 也会在内容上方长高时让 scrollTop 变化——方向上同样是"向下"，
  // 仅靠方向无法区分；有用户输入时间戳才能把用户的下滚从锚定位移里拆出来。
  const lastUserInputRef = useRef(Number.NEGATIVE_INFINITY)
  // 阅读锚点：用户上滚后记录"视口顶部附近的条目 + 它的屏幕位置"，此后内容在
  // 上方异步长高（历史任务的事件回放、图片加载、折叠展开）时按差值补 scrollTop，
  // 保证阅读位置漂移 <= 2px。程序化滚动/跟随底部时清空。
  const readingAnchorRef = useRef<{ element: HTMLElement; top: number } | null>(null)

  const clearExpected = useCallback(() => {
    expectedTopRef.current = null
    if (expectedTimerRef.current !== null) {
      window.clearTimeout(expectedTimerRef.current)
      expectedTimerRef.current = null
    }
  }, [])

  // Every scrollTop write goes through here and is tagged as expected so the
  // resulting scroll event can never be mistaken for a user scroll-up.
  const writeScrollTop = useCallback((top: number) => {
    const el = scrollRef.current
    if (!el) return
    if (Math.abs(el.scrollTop - top) <= 0.5) return
    expectedTopRef.current = top
    el.scrollTop = top
    if (expectedTimerRef.current !== null) {
      window.clearTimeout(expectedTimerRef.current)
    }
    expectedTimerRef.current = window.setTimeout(() => {
      expectedTopRef.current = null
      expectedTimerRef.current = null
    }, 600)
  }, [])

  // Pick the run/list item currently at the top of the viewport — the visual
  // anchor a reader expects to stay still while older history streams in above.
  const captureVisibleAnchor = useCallback(() => {
    const el = scrollRef.current
    const content = contentRef.current
    if (!el || !content) {
      readingAnchorRef.current = null
      return
    }
    const containerTop = el.getBoundingClientRect().top
    const candidates = content.querySelectorAll<HTMLElement>("ol > li, [data-thinking], [data-tool-id]")
    let best: HTMLElement | null = null
    let bestTop = 0
    for (const node of candidates) {
      const rect = node.getBoundingClientRect()
      if (rect.bottom <= containerTop + 1) continue
      best = node
      bestTop = rect.top
      break
    }
    readingAnchorRef.current = best ? { element: best, top: bestTop } : null
  }, [])

  // Keep the recorded anchor visually still after any layout-driven size change.
  const restoreReadingAnchor = useCallback(
    (el: HTMLElement) => {
      const anchor = readingAnchorRef.current
      if (!anchor) return
      if (!anchor.element.isConnected) {
        readingAnchorRef.current = null
        return
      }
      const delta = anchor.element.getBoundingClientRect().top - anchor.top
      if (Math.abs(delta) < 0.5) return
      writeScrollTop(el.scrollTop + delta)
    },
    [writeScrollTop],
  )

  const sync = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    lastContentSyncRef.current = performance.now()
    if (followingRef.current) {
      readingAnchorRef.current = null
      writeScrollTop(Math.max(0, el.scrollHeight - el.clientHeight))
      setShowJumpToLatest(false)
      return
    }
    restoreReadingAnchor(el)
    setShowJumpToLatest(distanceToBottom(el) > JUMP_DISTANCE)
  }, [writeScrollTop, restoreReadingAnchor])

  const onScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const distance = distanceToBottom(el)
    const previousTop = lastScrollTopRef.current
    lastScrollTopRef.current = el.scrollTop
    const expected = expectedTopRef.current
    const now = performance.now()
    if (expected !== null && Math.abs(el.scrollTop - expected) <= PROGRAMMATIC_TOLERANCE) {
      // Our own scroll write — never pauses follow.
      clearExpected()
    } else if (el.scrollTop < previousTop - PROGRAMMATIC_TOLERANCE) {
      // The user really moved upwards: follow only while within the threshold.
      followingRef.current = distance <= FOLLOW_DISTANCE
      if (!followingRef.current) captureVisibleAnchor()
    } else if (
      el.scrollTop > previousTop &&
      now - lastContentSyncRef.current < CONTENT_SYNC_GRACE_MS &&
      now - lastUserInputRef.current > CONTENT_SYNC_GRACE_MS
    ) {
      // Content grew above the viewport and the browser kept the visual anchor;
      // this is not a user scroll. Let the ResizeObserver settle it. The user
      // input window is checked too: a wheel-down arriving inside the grace
      // period is a real scroll — it must update the reading anchor, not be
      // silently undone by the next restoreReadingAnchor.
    } else {
      followingRef.current = distance <= FOLLOW_DISTANCE
      if (!followingRef.current) captureVisibleAnchor()
    }
    if (followingRef.current) readingAnchorRef.current = null
    setShowJumpToLatest(!followingRef.current && distance > JUMP_DISTANCE)
  }, [clearExpected, captureVisibleAnchor])

  const pauseFollow = useCallback(() => {
    const el = scrollRef.current
    followingRef.current = false
    captureVisibleAnchor()
    if (el) setShowJumpToLatest(distanceToBottom(el) > JUMP_DISTANCE)
  }, [captureVisibleAnchor])

  const onWheel = useCallback(
    (event: WheelEvent) => {
      if (findNestedScroller(event.target, scrollRef.current)) return
      lastUserInputRef.current = performance.now()
      if (event.deltaY < 0) pauseFollow()
    },
    [pauseFollow],
  )

  const onKeyDown = useCallback(
    (event: KeyboardEvent) => {
      const scrollKeys = new Set([
        "ArrowUp",
        "PageUp",
        "Home",
        "ArrowDown",
        "PageDown",
        "End",
      ])
      if (!scrollKeys.has(event.key)) return
      lastUserInputRef.current = performance.now()
      // Only upward intent pauses follow; downward keys land in onScroll and
      // resume following once the bottom threshold is reached.
      if (event.key === "ArrowUp" || event.key === "PageUp" || event.key === "Home") {
        pauseFollow()
      }
    },
    [pauseFollow],
  )

  const scrollToLatest = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    followingRef.current = true
    readingAnchorRef.current = null
    setShowJumpToLatest(false)
    writeScrollTop(Math.max(0, el.scrollHeight - el.clientHeight))
  }, [writeScrollTop])

  const captureAnchor = useCallback((): ScrollAnchor | null => {
    const el = scrollRef.current
    if (!el) return null
    return { scrollTop: el.scrollTop, scrollHeight: el.scrollHeight }
  }, [])

  const restoreAnchor = useCallback(
    (anchor: ScrollAnchor) => {
      const el = scrollRef.current
      if (!el) return
      // The user was paused mid-history, so we already recorded the element at
      // the top of the viewport. Older-run event replays land asynchronously and
      // grow the list above the reader, so restore from that element rather than
      // from a height delta that is only correct for the synchronous prepend.
      if (readingAnchorRef.current?.element.isConnected) {
        restoreReadingAnchor(el)
        return
      }
      const target = Math.max(
        0,
        Math.min(
          anchor.scrollTop + (el.scrollHeight - anchor.scrollHeight),
          el.scrollHeight - el.clientHeight,
        ),
      )
      if (Math.abs(el.scrollTop - target) > PROGRAMMATIC_TOLERANCE) writeScrollTop(target)
      captureVisibleAnchor()
    },
    [writeScrollTop, captureVisibleAnchor, restoreReadingAnchor],
  )

  const isFollowing = useCallback(() => followingRef.current, [])

  useLayoutEffect(() => {
    const el = scrollRef.current
    const content = contentRef.current
    followingRef.current = true
    readingAnchorRef.current = null
    setShowJumpToLatest(false)
    clearExpected()
    if (!el) return
    lastScrollTopRef.current = el.scrollTop
    // A chat log opens at the newest message, never at the top of history.
    el.scrollTop = Math.max(0, el.scrollHeight - el.clientHeight)
    lastScrollTopRef.current = el.scrollTop

    let touchStartY = 0
    const onTouchStart = (event: TouchEvent) => {
      touchStartY = event.touches[0]?.clientY ?? 0
    }
    const onTouchMove = (event: TouchEvent) => {
      const y = event.touches[0]?.clientY ?? 0
      if (Math.abs(y - touchStartY) > 4) {
        lastUserInputRef.current = performance.now()
      }
      if (y - touchStartY <= 4) return
      if (findNestedScroller(event.target, scrollRef.current)) return
      pauseFollow()
    }
    const onResize = () => sync()

    const scrollHandler = () => onScroll()
    el.addEventListener("scroll", scrollHandler, { passive: true })
    el.addEventListener("wheel", onWheel, { passive: true })
    el.addEventListener("touchstart", onTouchStart, { passive: true })
    el.addEventListener("touchmove", onTouchMove, { passive: true })
    el.addEventListener("keydown", onKeyDown)
    window.addEventListener("resize", onResize)

    let observer: ResizeObserver | null = null
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(onResize)
      observer.observe(el)
      if (content) observer.observe(content)
    }
    sync()

    return () => {
      el.removeEventListener("scroll", scrollHandler)
      el.removeEventListener("wheel", onWheel)
      el.removeEventListener("touchstart", onTouchStart)
      el.removeEventListener("touchmove", onTouchMove)
      el.removeEventListener("keydown", onKeyDown)
      window.removeEventListener("resize", onResize)
      observer?.disconnect()
      clearExpected()
    }
  }, [sessionKey, clearExpected, onKeyDown, onScroll, onWheel, pauseFollow, sync])

  return {
    scrollRef,
    contentRef,
    showJumpToLatest,
    isFollowing,
    scrollToLatest,
    captureAnchor,
    restoreAnchor,
  }
}