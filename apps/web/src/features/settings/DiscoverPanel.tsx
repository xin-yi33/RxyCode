// “拉取模型”结果区（MOD-07～11）：搜索过滤、复选/全选/清空、批量添加、
// 手动输入精确 model_id。逐项结果打标（已添加/已存在/无效），
// 失败不清已有列表；重复模型不重复入库（added 项勾选框禁用）。
import { useMemo, useState } from "react"

import { Button } from "../../components/ui/button"
import { IconSpinner } from "../../components/icons"
import {
  createClient,
  type AddModelResult,
  type DiscoveredModel,
  type DiscoverResult,
  type ModelConnection,
} from "../../sdk/client"
import { errorWithCode } from "../../sdk/errors"

const api = createClient()

const RESULT_TEXT: Record<string, string> = {
  added: "已添加",
  exists: "已存在",
  invalid: "无效",
}

const inputClass =
  "w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs " +
  "text-foreground outline-none focus:border-muted"

export function DiscoverPanel({
  connection,
  result,
  busy,
  fetchError,
  onRetry,
  onChanged,
}: {
  connection: ModelConnection
  // null = 尚未返回/正在拉取。
  result: DiscoverResult | null
  busy: boolean
  fetchError: string
  onRetry: () => void
  onChanged: () => void
}) {
  const [filter, setFilter] = useState("")
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState("")
  const [outcomes, setOutcomes] = useState<Record<string, AddModelResult["status"]>>({})
  const [manualId, setManualId] = useState("")

  const items = useMemo(() => result?.models ?? [], [result])
  const filtered = useMemo(() => {
    const f = filter.trim().toLowerCase()
    if (!f) return items
    return items.filter((item) =>
      `${item.id} ${item.name ?? ""}`.toLowerCase().includes(f),
    )
  }, [items, filter])
  // 已在目录（added）或本次刚添加成功的项不可再选。
  const selectable = filtered.filter(
    (item) => !item.added && outcomes[item.id] !== "added",
  )
  const checkedCount = selectable.filter((item) => selected.has(item.id)).length
  const allChecked = selectable.length > 0 && checkedCount === selectable.length

  const toggle = (item: DiscoveredModel, on: boolean) => {
    setSelected((current) => {
      const next = new Set(current)
      if (on) next.add(item.id)
      else next.delete(item.id)
      return next
    })
  }

  const submit = async (modelIds: string[]): Promise<boolean> => {
    if (adding || modelIds.length === 0) return false
    setAdding(true)
    setAddError("")
    try {
      const { results } = await api.addConnectionModels(connection.id, modelIds)
      const added: string[] = []
      setOutcomes((current) => {
        const next = { ...current }
        for (const row of results) {
          next[row.model_id] = row.status
          if (row.status === "added") added.push(row.model_id)
        }
        return next
      })
      setSelected((current) => {
        const next = new Set(current)
        for (const id of added) next.delete(id)
        return next
      })
      if (results.some((row) => row.status === "added")) onChanged()
      return true
    } catch (err) {
      setAddError(errorWithCode(err))
      return false
    } finally {
      setAdding(false)
    }
  }

  return (
    <div className="mt-3 rounded-lg border border-border bg-sidebar p-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs font-medium">拉取到的可用模型</p>
        <span className="text-xs text-muted">
          {result
            ? `${items.length} 个 · ${result.elapsed != null ? `${result.elapsed}s` : ""}`
            : ""}
        </span>
        <button
          type="button"
          className="ml-auto text-xs text-muted-ink underline disabled:opacity-60"
          disabled={busy}
          onClick={onRetry}
        >
          重新拉取
        </button>
      </div>
      {busy && !result ? (
        <p className="py-3 text-xs text-muted">
          <IconSpinner size={12} className="mr-1 inline-block" />
          正在拉取模型列表…
        </p>
      ) : null}
      {fetchError ? (
        <p role="alert" className="mt-2 text-xs text-failure">
          {fetchError}
        </p>
      ) : null}
      {result && !result.success ? (
        <p role="alert" className="mt-2 text-xs text-failure">
          发现失败{result.error ? `：${result.error}` : ""}
          {result.error_code ? `（${result.error_code}）` : ""}
        </p>
      ) : null}
      {result?.success ? (
        <>
          <div className="mt-2 flex items-center gap-2">
            <input
              className={inputClass + " min-w-0 flex-1"}
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="搜索模型…"
              aria-label="搜索发现结果"
            />
            <button
              type="button"
              className="shrink-0 text-xs text-muted-ink underline disabled:opacity-60"
              disabled={selectable.length === 0 || allChecked}
              onClick={() =>
                setSelected((current) => {
                  const next = new Set(current)
                  for (const item of selectable) next.add(item.id)
                  return next
                })
              }
            >
              全选（{selectable.length}）
            </button>
            <button
              type="button"
              className="shrink-0 text-xs text-muted-ink underline disabled:opacity-60"
              disabled={checkedCount === 0}
              onClick={() =>
                setSelected((current) => {
                  const next = new Set(current)
                  for (const item of selectable) next.delete(item.id)
                  return next
                })
              }
            >
              清空
            </button>
          </div>
          <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto">
            {filtered.map((item) => {
              // 已在目录的项：勾选框禁用且呈已选态，芯片标“已添加”（MOD-10）。
              const status: AddModelResult["status"] | "added" = item.added
                ? "added"
                : (outcomes[item.id] ?? "")
              const locked = Boolean(item.added) || status === "added"
              return (
                <li
                  key={item.id}
                  className="flex items-center gap-2 rounded-md bg-card px-2 py-1.5"
                >
                  <input
                    type="checkbox"
                    aria-label={`选择 ${item.id}`}
                    checked={locked ? true : selected.has(item.id)}
                    disabled={locked || adding}
                    onChange={(event) => toggle(item, event.target.checked)}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs">
                      {item.name || item.id}
                    </span>
                    {item.name ? (
                      <span className="block truncate font-mono text-[10px] text-muted">
                        {item.id}
                      </span>
                    ) : null}
                  </span>
                  {status ? (
                    <span
                      className={
                        "shrink-0 rounded-full px-1.5 py-0.5 text-[10px] " +
                        (status === "added"
                          ? "bg-success/15 text-success-ink"
                          : status === "invalid"
                            ? "bg-failure/15 text-failure-ink"
                            : "bg-border text-muted-ink")
                      }
                    >
                      {RESULT_TEXT[status] ?? status}
                    </span>
                  ) : null}
                </li>
              )
            })}
            {filtered.length === 0 ? (
              <li className="px-1 py-2 text-xs text-muted">
                没有匹配“{filter}”的结果
              </li>
            ) : null}
          </ul>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              disabled={adding || checkedCount === 0}
              onClick={() =>
                void submit(
                  selectable
                    .filter((item) => selected.has(item.id))
                    .map((item) => item.id),
                )
              }
            >
              {adding ? "添加中…" : `添加所选模型（${checkedCount}）`}
            </Button>
            <span className="min-w-0 flex-1" />
          </div>
          <div className="mt-2 flex items-center gap-2">
            <input
              className={inputClass + " min-w-0 flex-1 font-mono"}
              value={manualId}
              onChange={(event) => setManualId(event.target.value)}
              placeholder="手动添加模型 ID"
              aria-label="手动添加模型 ID"
            />
            <Button
              variant="outline"
              size="sm"
              className="shrink-0"
              disabled={adding || !manualId.trim()}
              onClick={() => {
                const id = manualId.trim()
                // 成功才清空输入框；失败保留便于修正重试。
                void submit([id]).then((ok) => {
                  if (ok) setManualId("")
                })
              }}
            >
              添加
            </Button>
          </div>
          {addError ? (
            <p role="alert" className="mt-2 text-xs text-failure">
              {addError}
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
