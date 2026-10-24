import { cn } from "../lib/cn"
import { FileTypeIcon } from "./FileTypeIcon"

// UI-09: one shared filename renderer. Long names keep their extension (and
// compound suffixes such as .tar.gz) visible while the stem gets a middle
// ellipsis; short names pass through untouched. The real name always stays in
// `title` + `aria-label` (download attributes are set by the callers).

export const MAX_FILE_NAME_CHARS = 38

const COMPOUND_SUFFIXES = [
  ".tar.gz",
  ".tar.bz2",
  ".tar.xz",
  ".tar.zst",
  ".tar.lz",
  ".tar.lzma",
  ".tar.z",
] as const

export type SplitFileName = {
  stem: string
  suffix: string
}

export function splitFileName(name: string): SplitFileName {
  const lower = name.toLowerCase()
  for (const suffix of COMPOUND_SUFFIXES) {
    if (lower.endsWith(suffix) && name.length > suffix.length) {
      return {
        stem: name.slice(0, name.length - suffix.length),
        suffix: name.slice(-suffix.length),
      }
    }
  }
  const dot = name.lastIndexOf(".")
  // Leading-dot dotfiles (.gitignore) have no stem to shorten; keep the whole
  // name as the stem so the visible text never starts with a dangling "…".
  if (dot > 0 && dot < name.length - 1) {
    return { stem: name.slice(0, dot), suffix: name.slice(dot) }
  }
  return { stem: name, suffix: "" }
}

export type DisplayFileName = {
  /** Visible, possibly ellipsized stem. */
  head: string
  /** Visible, never-truncated extension cell. */
  suffix: string
}

// Text budget is deliberate: the head cell also truncates via CSS, so narrow
// containers still keep the suffix cell (shrink-0) and a responsive layout.
export function splitForDisplay(
  name: string,
  maxChars: number = MAX_FILE_NAME_CHARS,
): DisplayFileName {
  const { stem, suffix } = splitFileName(name)
  if (name.length <= maxChars) return { head: stem, suffix }
  // The suffix always wins budget over the stem.
  const headBudget = Math.max(1, maxChars - suffix.length - 1)
  return { head: `${stem.slice(0, headBudget)}…`, suffix }
}

export function middleEllipsis(name: string, maxChars: number = MAX_FILE_NAME_CHARS): string {
  const { head, suffix } = splitForDisplay(name, maxChars)
  return `${head}${suffix}`
}

export type FileNameProps = {
  /** Full filename — also used by tools/tests as the accessible name. */
  name: string
  /** Optional longer context (e.g. a session file path) for title/aria-label. */
  title?: string
  className?: string
  testId?: string
  /** 默认按扩展名渲染类型图标（Windows 资源管理器式类别着色）；传 false 关闭。 */
  icon?: boolean
}

export function FileName({
  name,
  title,
  className,
  testId = "chat-file-name",
  icon = true,
}: FileNameProps) {
  const accessible = title ?? name
  const { head, suffix } = splitForDisplay(name)
  return (
    <span
      data-testid={testId}
      title={accessible}
      aria-label={accessible}
      className={cn(
        // Header/row friendly: the suffix cell never shrinks, the head cell
        // truncates, so the extension survives any width the surface gives us.
        "inline-flex min-w-0 max-w-full items-center gap-1.5 overflow-hidden whitespace-nowrap",
        className,
      )}
    >
      {icon ? (
        <FileTypeIcon name={name} size={15} className="shrink-0" />
      ) : null}
      <span className="flex min-w-0 items-baseline overflow-hidden">
        <span aria-hidden="true" className="min-w-0 truncate">
          {head}
        </span>
        {suffix ? (
          <span aria-hidden="true" className="shrink-0">
            {suffix}
          </span>
        ) : null}
      </span>
    </span>
  )
}
