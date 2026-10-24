import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react"

import { clsx } from "clsx"

import {
  clampLeftRatio,
  DEFAULT_LEFT_RATIO,
  KEYBOARD_STEP,
  MIN_LEFT_RATIO,
  prefersReducedMotion,
  ratioFromPointerX,
  ratioPercent,
  runSpring,
  shouldCollapsePreview,
  SNAP_LEFT_RATIO,
  SNAP_TOLERANCE,
  SPRING,
  type SpringConfig,
  type SpringHandle,
  type SplitState,
} from "./split"

export type PreviewPaneMode = "pane" | "overlay"

export type PreviewPaneControls = {
  mode: PreviewPaneMode
  /** Rigid spring back to 50/50 (same caller family as double-click). */
  resetSplit: () => void
}

// PreviewDrawer consumes this to pick pane vs fullscreen-overlay chrome and
// to expose the "重置分栏" action; Esc stays owned by SplitWorkspace so the
// pre-drag snapshot can be restored before anything closes.
const PreviewPaneContext = createContext<PreviewPaneControls | null>(null)

export function usePreviewPane(): PreviewPaneControls | null {
  return useContext(PreviewPaneContext)
}

type DragSnapshot = {
  leftRatio: number
  previewOpen: boolean
  pointerId: number
}

type DragSession = {
  pointerId: number
  rawRatio: number
}

export type SplitWorkspaceProps = {
  /** Live preview surface. null/undefined means the preview is closed. */
  preview?: ReactNode | null
  /** Dismiss the preview (close button / Esc without a drag snapshot). */
  onPreviewClose: () => void
  /**
   * Bump this whenever the user explicitly (re)selects an artifact preview.
   * preview data arriving after a drag-collapse keeps previewOpen=false, so a
   * data-only change cannot reopen the pane — an explicit signal can.
   */
  openSignal?: number
  /** Chat column (scroll container + composer) supplied by the page. */
  children: ReactNode
}

const SMALL_VIEWPORT = "(max-width: 767px)"

function useSmallViewport(): boolean {
  const [small, setSmall] = useState(
    () => typeof window !== "undefined" && window.matchMedia(SMALL_VIEWPORT).matches,
  )
  useEffect(() => {
    const query = window.matchMedia(SMALL_VIEWPORT)
    const sync = () => setSmall(query.matches)
    sync()
    query.addEventListener("change", sync)
    return () => query.removeEventListener("change", sync)
  }, [])
  return small
}

// UI-08: real draggable split between the chat column and the preview pane.
// Desktop gets a width-based split (the chat area actually narrows); phones
// keep the chat full-width and show the preview as a fullscreen overlay.
// The drag itself is direct-follow; only reset/confirm transitions animate.
export function SplitWorkspace({
  preview,
  onPreviewClose,
  openSignal = 0,
  children,
}: SplitWorkspaceProps) {
  const small = useSmallViewport()
  const mode: PreviewPaneMode = small ? "overlay" : "pane"
  const hasPreview = preview !== null && preview !== undefined

  // previewOpen starts true: SplitWorkspace only renders its split chrome while
  // a preview exists (it is layout-transparent otherwise), so a freshly opened
  // preview is split immediately instead of flashing full width for a frame.
  const [split, setSplit] = useState<SplitState>({
    leftRatio: DEFAULT_LEFT_RATIO,
    previewOpen: true,
  })
  const [dragging, setDragging] = useState(false)

  const rootRef = useRef<HTMLDivElement | null>(null)
  const handleRef = useRef<HTMLDivElement | null>(null)
  const splitRef = useRef(split)
  splitRef.current = split
  const snapshotRef = useRef<DragSnapshot | null>(null)
  const dragRef = useRef<DragSession | null>(null)
  const cleanupListenersRef = useRef<(() => void) | null>(null)
  const springRef = useRef<SpringHandle | null>(null)

  const cancelSpring = useCallback(() => {
    springRef.current?.cancel()
    springRef.current = null
  }, [])

  const commitRatio = useCallback((ratio: number) => {
    splitRef.current = { ...splitRef.current, leftRatio: ratio }
    setSplit((current) => ({ ...current, leftRatio: ratio }))
  }, [])

  const animateTo = useCallback(
    (target: number, config: SpringConfig) => {
      cancelSpring()
      const from = splitRef.current.leftRatio
      if (from === target) {
        commitRatio(target)
        return
      }
      const handle = runSpring({
        config,
        from,
        to: target,
        reducedMotion: prefersReducedMotion(),
        onUpdate: (value) => commitRatio(clampLeftRatio(value)),
        onSettled: () => {
          springRef.current = null
          commitRatio(target)
        },
      })
      springRef.current = handle
    },
    [cancelSpring, commitRatio],
  )

  const resetSplit = useCallback(() => {
    animateTo(SNAP_LEFT_RATIO, SPRING.rigid)
  }, [animateTo])

  // Data availability plus the explicit open signal drive previewOpen; a drag
  // can collapse the pane without clearing the preview data, which is what
  // makes Esc able to restore it — and a fresh openSignal (artifact reselected)
  // is what reopens a collapsed pane even while hasPreview stayed true.
  useEffect(() => {
    if (hasPreview) {
      setSplit((current) => (current.previewOpen ? current : { ...current, previewOpen: true }))
      return
    }
    snapshotRef.current = null
    setSplit((current) =>
      current.previewOpen || current.leftRatio !== DEFAULT_LEFT_RATIO
        ? { leftRatio: DEFAULT_LEFT_RATIO, previewOpen: true }
        : current,
    )
  }, [hasPreview, openSignal])

  // Desktop -> phone resize must not leave a collapsed preview invisible.
  useEffect(() => {
    if (mode === "overlay" && hasPreview) {
      setSplit((current) => (current.previewOpen ? current : { ...current, previewOpen: true }))
    }
  }, [mode, hasPreview])

  useEffect(
    () => () => {
      cancelSpring()
      cleanupListenersRef.current?.()
      cleanupListenersRef.current = null
      dragRef.current = null
    },
    [cancelSpring],
  )

  const endDrag = useCallback(
    (revert: boolean) => {
      const drag = dragRef.current
      if (!drag) return
      dragRef.current = null
      cleanupListenersRef.current?.()
      cleanupListenersRef.current = null
      setDragging(false)
      const handle = handleRef.current
      if (handle) {
        try {
          if (handle.hasPointerCapture?.(drag.pointerId)) {
            handle.releasePointerCapture(drag.pointerId)
          }
        } catch {
          // The pointer is already gone; nothing to release.
        }
      }
      if (revert) {
        const snapshot = snapshotRef.current
        if (snapshot) {
          setSplit({ leftRatio: snapshot.leftRatio, previewOpen: snapshot.previewOpen })
        }
        return
      }
      if (shouldCollapsePreview(drag.rawRatio)) {
        const collapsed = clampLeftRatio(drag.rawRatio)
        splitRef.current = { leftRatio: collapsed, previewOpen: false }
        setSplit({ leftRatio: collapsed, previewOpen: false })
        return
      }
      const settled = clampLeftRatio(drag.rawRatio)
      splitRef.current = { leftRatio: settled, previewOpen: true }
      setSplit({ leftRatio: settled, previewOpen: true })
      // Small confirm: nudge the dropped divider onto exact 50/50.
      if (Math.abs(settled - SNAP_LEFT_RATIO) <= SNAP_TOLERANCE) {
        animateTo(SNAP_LEFT_RATIO, SPRING.confirm)
      }
    },
    [animateTo],
  )

  const onHandleLostPointerCapture = useCallback(() => {
    // Capture can be stolen (window switch, element removal); treat it as cancel.
    if (dragRef.current) endDrag(true)
  }, [endDrag])

  const onHandlePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (event.pointerType === "mouse" && event.button !== 0) return
      if (dragRef.current) return
      cancelSpring()
      const base = splitRef.current
      snapshotRef.current = {
        leftRatio: base.leftRatio,
        previewOpen: base.previewOpen,
        pointerId: event.pointerId,
      }
      dragRef.current = { pointerId: event.pointerId, rawRatio: base.leftRatio }
      setDragging(true)
      const target = event.currentTarget
      try {
        target.setPointerCapture(event.pointerId)
      } catch {
        // Synthetic pointerdown events have no active pointer to capture.
      }

      const applyPointer = (clientX: number) => {
        const drag = dragRef.current
        const root = rootRef.current
        if (!drag || !root) return
        const rect = root.getBoundingClientRect()
        const raw = ratioFromPointerX(clientX, rect)
        drag.rawRatio = raw
        const collapsed = shouldCollapsePreview(raw)
        const next: SplitState = { leftRatio: clampLeftRatio(raw), previewOpen: !collapsed }
        splitRef.current = next
        setSplit(next)
      }

      const onPointerMove = (moveEvent: PointerEvent) => {
        if (moveEvent.pointerId !== dragRef.current?.pointerId) return
        applyPointer(moveEvent.clientX)
      }
      const onPointerUp = (upEvent: PointerEvent) => {
        if (upEvent.pointerId !== dragRef.current?.pointerId) return
        endDrag(false)
      }
      const onPointerCancel = () => endDrag(true)
      const onWindowBlur = () => endDrag(true)

      window.addEventListener("pointermove", onPointerMove)
      window.addEventListener("pointerup", onPointerUp)
      window.addEventListener("pointercancel", onPointerCancel)
      window.addEventListener("blur", onWindowBlur)
      cleanupListenersRef.current = () => {
        window.removeEventListener("pointermove", onPointerMove)
        window.removeEventListener("pointerup", onPointerUp)
        window.removeEventListener("pointercancel", onPointerCancel)
        window.removeEventListener("blur", onWindowBlur)
      }
    },
    [cancelSpring, endDrag],
  )

  const onHandleDoubleClick = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      event.preventDefault()
      animateTo(SNAP_LEFT_RATIO, SPRING.rigid)
    },
    [animateTo],
  )

  const onHandleKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault()
        const step = event.key === "ArrowLeft" ? -KEYBOARD_STEP : KEYBOARD_STEP
        animateTo(clampLeftRatio(splitRef.current.leftRatio + step), SPRING.confirm)
        return
      }
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault()
        animateTo(SNAP_LEFT_RATIO, SPRING.rigid)
      }
    },
    [animateTo],
  )

  // One Esc owner: restoring the pre-drag snapshot wins and swallows the key so
  // the preview does not additionally close (that is the required behaviour).
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      const snapshot = snapshotRef.current
      if (snapshot) {
        event.preventDefault()
        event.stopPropagation()
        event.stopImmediatePropagation()
        snapshotRef.current = null
        cancelSpring()
        dragRef.current = null
        cleanupListenersRef.current?.()
        cleanupListenersRef.current = null
        setDragging(false)
        setSplit({ leftRatio: snapshot.leftRatio, previewOpen: snapshot.previewOpen })
        return
      }
      if (!hasPreview) return
      // A modal layer above the console keeps Esc for itself.
      if (document.querySelector("dialog[open]")) return
      event.preventDefault()
      onPreviewClose()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [hasPreview, onPreviewClose, cancelSpring])

  const paneControls = useMemo<PreviewPaneControls>(
    () => ({ mode, resetSplit }),
    [mode, resetSplit],
  )

  const showSplit = hasPreview && mode === "pane" && split.previewOpen

  // The chat subtree must never remount when a preview opens/closes — a
  // fragment->wrapper switch would discard Composer's pending attachments and
  // strand useChatScrollController's listeners on detached nodes. Both wrapper
  // divs therefore stay mounted permanently and degrade to display:contents
  // while inactive (layout-identical to the page before the split existed).
  return (
    <div
      ref={rootRef}
      data-testid="chat-preview-split"
      data-preview-mode={mode}
      data-preview-open={showSplit ? "true" : "false"}
      className={clsx(
        "relative flex h-full min-h-0 w-full overflow-hidden",
        dragging && "cursor-col-resize select-none",
      )}
      style={hasPreview ? undefined : { display: "contents" }}
    >
      <div
        data-preview-chat-pane
        className={clsx("flex h-full min-h-0 min-w-0 flex-col")}
        style={
          !hasPreview
            ? { display: "contents" }
            : showSplit
              ? { width: `${split.leftRatio * 100}%` }
              : { width: "100%" }
        }
      >
        {children}
      </div>
      {showSplit ? (
        <div
          data-preview-pane
          className="relative flex h-full min-h-0 min-w-0 flex-1 flex-col border-l border-border bg-card"
        >
          <PreviewPaneContext.Provider value={paneControls}>
            <div className="flex h-full min-h-0 flex-col">{preview}</div>
          </PreviewPaneContext.Provider>
          <div
            ref={handleRef}
            data-testid="chat-preview-handle"
            role="separator"
            aria-label="调整预览分栏"
            aria-orientation="vertical"
            aria-valuemin={ratioPercent(MIN_LEFT_RATIO)}
            aria-valuemax={100}
            aria-valuenow={ratioPercent(split.leftRatio)}
            title="拖动调整预览宽度，双击恢复 50/50"
            tabIndex={0}
            className={clsx(
              "group absolute inset-y-0 left-0 z-20 w-2 -translate-x-1/2 cursor-col-resize",
              "touch-none select-none bg-transparent outline-none",
            )}
            onPointerDown={onHandlePointerDown}
            onDoubleClick={onHandleDoubleClick}
            onKeyDown={onHandleKeyDown}
            onLostPointerCapture={onHandleLostPointerCapture}
          >
            <span
              aria-hidden="true"
              className={clsx(
                "pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border",
                "transition-colors group-hover:bg-muted group-focus:bg-running",
              )}
            />
          </div>
        </div>
      ) : null}
      {hasPreview && mode === "overlay" ? (
        <PreviewPaneContext.Provider value={paneControls}>{preview}</PreviewPaneContext.Provider>
      ) : null}
      {dragging ? (
        <div
          aria-hidden="true"
          data-preview-drag-overlay
          className="absolute inset-0 z-30 cursor-col-resize touch-none"
        />
      ) : null}
    </div>
  )
}
