import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router"

import { IconClose, IconSearch, IconSpinner } from "../../components/icons"
import { useI18n } from "../../lib/i18n"
import { createClient, type SearchHit } from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { useUi } from "../../state/ui"

const api = createClient()

const TYPES = [
  { id: "all", label: "全部" },
  { id: "chat", label: "会话" },
  { id: "project", label: "项目" },
  { id: "image", label: "图片" },
  { id: "document", label: "文档" },
] as const

const DEBOUNCE_MS = 250

export function SearchModal() {
  const open = useUi((s) => s.searchOpen)
  const setOpen = useUi((s) => s.setSearchOpen)
  const navigate = useNavigate()
  const { t } = useI18n()

  const [query, setQuery] = useState("")
  const [type, setType] = useState<(typeof TYPES)[number]["id"]>("all")
  const [hits, setHits] = useState<SearchHit[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [active, setActive] = useState(0)
  const [composing, setComposing] = useState(false)

  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const debounceRef = useRef<number | null>(null)
  const requestSeq = useRef(0)

  const runSearch = useCallback(
    (q: string, searchType: string, appendCursor: string | null) => {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      const seq = ++requestSeq.current
      setLoading(true)
      setError("")
      api
        .search(
          { q, type: searchType, cursor: appendCursor ?? undefined, limit: 20 },
          controller.signal,
        )
        .then((res) => {
          if (seq !== requestSeq.current) return // stale response
          setHits((prev) => (appendCursor ? [...prev, ...res.hits] : res.hits))
          setCursor(res.next_cursor)
        })
        .catch((err: unknown) => {
          if ((err as Error).name === "AbortError") return
          if (seq !== requestSeq.current) return
          setError(apiErrorText(err))
        })
        .finally(() => {
          if (seq === requestSeq.current) setLoading(false)
        })
    },
    [],
  )

  // Debounce input → search; IME composition never fires mid-edit.
  useEffect(() => {
    if (!open || composing) return
    if (debounceRef.current) window.clearTimeout(debounceRef.current)
    debounceRef.current = window.setTimeout(() => {
      setActive(0)
      runSearch(query.trim(), type, null)
    }, DEBOUNCE_MS)
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current)
    }
  }, [query, type, open, composing, runSearch])

  useEffect(() => {
    if (!open) return
    setQuery("")
    setHits([])
    setCursor(null)
    setType("all")
    setActive(0)
    setError("")
    const frame = requestAnimationFrame(() => inputRef.current?.focus())
    return () => {
      cancelAnimationFrame(frame)
      abortRef.current?.abort()
    }
  }, [open])

  // Global Ctrl+K / Cmd+K toggle.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setOpen(!useUi.getState().searchOpen)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [setOpen])

  if (!open) return null

  const go = (hit: SearchHit) => {
    setOpen(false)
    navigate(hit.href)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault()
      setOpen(false)
    } else if (e.key === "ArrowDown") {
      e.preventDefault()
      setActive((i) => Math.min(i + 1, hits.length - 1))
      listRef.current
        ?.querySelector(`[data-index="${Math.min(active + 1, hits.length - 1)}"]`)
        ?.scrollIntoView({ block: "nearest" })
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === "Enter" && hits[active]) {
      e.preventDefault()
      go(hits[active])
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh]"
      role="dialog"
      aria-modal="true"
      aria-label={t("app.search")}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setOpen(false)
      }}
    >
      <div className="w-full max-w-xl overflow-hidden rounded-xl border border-border bg-card shadow-xl">
        <div className="flex items-center gap-2 border-b border-border px-3">
          <IconSearch size={16} className="shrink-0 text-muted" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onCompositionStart={() => setComposing(true)}
            onCompositionEnd={() => {
              setComposing(false)
              setQuery((v) => v)
            }}
            onKeyDown={onKeyDown}
            placeholder={t("search.placeholder")}
            aria-label={t("search.placeholder")}
            className="h-11 flex-1 bg-transparent text-sm outline-none"
          />
          {loading ? <IconSpinner size={15} className="text-muted" /> : null}
          <button
            type="button"
            aria-label={t("search.closeTip")}
            className="rounded p-1 text-muted hover:bg-background"
            onClick={() => setOpen(false)}
          >
            <IconClose size={15} />
          </button>
        </div>
        <div className="flex gap-1 border-b border-border px-3 py-2" role="tablist">
          {TYPES.map((chip) => (
            <button
              key={chip.id}
              type="button"
              role="tab"
              aria-selected={type === chip.id}
              onClick={() => setType(chip.id)}
              className={
                "rounded-full px-2.5 py-1 text-xs " +
                (type === chip.id
                  ? "bg-foreground text-background"
                  : "text-muted hover:bg-background")
              }
            >
              {chip.label}
            </button>
          ))}
        </div>
        {error ? (
          <p role="alert" className="px-4 py-3 text-sm text-failure">
            {error}{" "}
            <button
              type="button"
              className="underline"
              onClick={() => runSearch(query.trim(), type, null)}
            >
              {t("app.retry")}
            </button>
          </p>
        ) : null}
        <ul ref={listRef} role="listbox" className="max-h-[50vh] overflow-y-auto py-1">
          {hits.length === 0 && !loading ? (
            <li className="px-4 py-6 text-center text-sm text-muted">
              {query.trim() ? t("search.noResults") : t("search.empty")}
            </li>
          ) : (
            hits.map((hit, i) => (
              <li key={`${hit.type}:${hit.id}`} role="option" aria-selected={i === active} data-index={i}>
                <button
                  type="button"
                  onClick={() => go(hit)}
                  onMouseEnter={() => setActive(i)}
                  className={
                    "flex w-full flex-col gap-0.5 px-4 py-2.5 text-left " +
                    (i === active ? "bg-background" : "")
                  }
                >
                  <span className="flex items-center gap-2 text-sm">
                    <span className="rounded bg-border px-1.5 py-0.5 text-[10px] uppercase text-muted-ink">
                      {hit.type}
                    </span>
                    <span className="truncate font-medium">{hit.title || "—"}</span>
                  </span>
                  {hit.snippet ? (
                    <span className="truncate text-xs text-muted">{hit.snippet}</span>
                  ) : null}
                </button>
              </li>
            ))
          )}
        </ul>
        {cursor ? (
          <div className="border-t border-border px-4 py-2">
            <button
              type="button"
              disabled={loading}
              onClick={() => runSearch(query.trim(), type, cursor)}
              className="text-sm text-muted underline disabled:opacity-60"
            >
              {t("search.loadMore")}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
