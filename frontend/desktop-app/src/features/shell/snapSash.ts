/**
 * Codex/VS Code sash: collapse or preferred on the way in; free grow to max;
 * shrinking from max dwells at preferred before collapsing.
 * Algorithm adapted from vscode sash snap + allotment Pane.snap.
 */

export type SashAxis = 'horizontal' | 'vertical'
export type SashBand = 'collapsed' | 'preferred' | 'free'

export interface SnapSpec {
  preferred: number
  max: number
  dwellMs: number
}

export const WORKBENCH_PANES_KEY = 'rxycode.desktop.workbench.v1'

export interface WorkbenchPanes {
  left: number
  right: number
  bottom: number
}

export const DEFAULT_WORKBENCH_PANES: WorkbenchPanes = {
  left: 248,
  right: 360,
  bottom: 180
}

export function loadWorkbenchPanes(storage: Pick<Storage, 'getItem'>): WorkbenchPanes {
  const raw = storage.getItem(WORKBENCH_PANES_KEY)
  if (raw === null) return { ...DEFAULT_WORKBENCH_PANES }
  try {
    const value = JSON.parse(raw) as Partial<WorkbenchPanes>
    return {
      left: Number.isFinite(value.left) ? Math.max(0, Number(value.left)) : DEFAULT_WORKBENCH_PANES.left,
      right: Number.isFinite(value.right) ? Math.max(0, Number(value.right)) : DEFAULT_WORKBENCH_PANES.right,
      bottom: Number.isFinite(value.bottom) ? Math.max(0, Number(value.bottom)) : DEFAULT_WORKBENCH_PANES.bottom
    }
  } catch {
    return { ...DEFAULT_WORKBENCH_PANES }
  }
}

export function saveWorkbenchPanes(panes: WorkbenchPanes, storage: Pick<Storage, 'setItem'>): void {
  storage.setItem(WORKBENCH_PANES_KEY, JSON.stringify(panes))
}

export const LEFT_SNAP: SnapSpec = { preferred: 248, max: 520, dwellMs: 280 }
export const RIGHT_SNAP: SnapSpec = { preferred: 360, max: 640, dwellMs: 280 }
export const BOTTOM_SNAP: SnapSpec = { preferred: 180, max: 420, dwellMs: 280 }

export interface SnapDrag {
  origin: SashBand
  proposed: number
  now: number
  dwellStartedAt: number | null
}

export interface SnapResult {
  size: number
  band: SashBand
  dwellStartedAt: number | null
  snap: boolean
}

export function bandOf(size: number, spec: SnapSpec): SashBand {
  if (size <= 0) return 'collapsed'
  if (size <= spec.preferred) return 'preferred'
  return 'free'
}

export function clampPanelSize(size: number, spec: SnapSpec): number {
  if (size <= 0) return 0
  return Math.min(spec.max, Math.max(spec.preferred, size))
}

export function applySnapDrag(spec: SnapSpec, drag: SnapDrag): SnapResult {
  const proposed = Math.max(0, Math.min(spec.max, drag.proposed))
  if (drag.origin === 'collapsed') {
    const openPx = Math.min(72, spec.preferred * 0.4)
    if (proposed < openPx) {
      return { size: 0, band: 'collapsed', dwellStartedAt: null, snap: false }
    }
    if (proposed <= spec.preferred) {
      return { size: spec.preferred, band: 'preferred', dwellStartedAt: null, snap: true }
    }
    return { size: proposed, band: 'free', dwellStartedAt: null, snap: false }
  }
  if (drag.origin === 'preferred') {
    if (proposed >= spec.preferred) {
      const size = Math.min(spec.max, proposed)
      return {
        size,
        band: size > spec.preferred ? 'free' : 'preferred',
        dwellStartedAt: null,
        snap: false
      }
    }
    return { size: 0, band: 'collapsed', dwellStartedAt: null, snap: true }
  }
  if (proposed >= spec.preferred) {
    const size = Math.min(spec.max, proposed)
    return {
      size,
      band: size > spec.preferred ? 'free' : 'preferred',
      dwellStartedAt: null,
      snap: false
    }
  }
  if (drag.dwellStartedAt === null) {
    return { size: spec.preferred, band: 'preferred', dwellStartedAt: drag.now, snap: true }
  }
  if (drag.now - drag.dwellStartedAt < spec.dwellMs) {
    return { size: spec.preferred, band: 'preferred', dwellStartedAt: drag.dwellStartedAt, snap: false }
  }
  return { size: 0, band: 'collapsed', dwellStartedAt: null, snap: true }
}
