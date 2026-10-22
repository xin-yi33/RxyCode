// “模型与 BYOK”设置区（SET-02）：连接列表（表格 ≥640px / 卡片 <640px）、
// 全部连接操作（编辑/拉取模型/测试/清除 Key/删除）与模型目录
// （默认 ★ / 删除 / 计费测试确认）。私有数据显式三态（骨架/错误卡/内容）。
import { useEffect, useState, type ReactNode } from "react"

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { Button } from "../../components/ui/button"
import { ConfirmDialog } from "../../components/ui/dialog"
import {
  IconPlus,
  IconRefresh,
  IconSpinner,
  IconStar,
  IconTrash,
} from "../../components/icons"
import {
  createClient,
  type ConnectionTestResult,
  type DiscoverResult,
  type ModelConnection,
  type ModelItem,
} from "../../sdk/client"
import { errorWithCode } from "../../sdk/errors"
import {
  invalidateModelQueries,
  useModelConnections,
  useModelProviders,
  useModelsAccess,
  useModelsCatalog,
} from "../models/queries"
import { ConnectionFormDialog } from "./ConnectionFormDialog"
import { DiscoverPanel } from "./DiscoverPanel"

const api = createClient()

// conn.state 目前只会是 "active"（后端无其它赋值），这里容错显示原始值。
const CONN_STATE_TEXT: Record<string, string> = {
  active: "正常",
}

const TEST_STATUS_TEXT: Record<string, string> = {
  untested: "未测试",
  ok: "通过",
  failed: "失败",
}

const MODEL_STATUS_TEXT: Record<string, string> = {
  available: "可用",
  revoked: "连接已变更",
  no_key: "未配置密钥",
}

function Card({
  title,
  action,
  children,
}: {
  title: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="text-sm font-semibold">{title}</h3>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </section>
  )
}

function SkeletonRows() {
  // 显式骨架（MOD-00）：不用伪装数据。
  return (
    <div className="space-y-2" aria-busy="true" aria-label="正在加载">
      <div className="h-4 w-1/2 animate-pulse rounded bg-border" />
      <div className="h-4 w-3/4 animate-pulse rounded bg-border" />
      <div className="h-4 w-2/3 animate-pulse rounded bg-border" />
      <p className="pt-1 text-xs text-muted">正在加载模型设置…</p>
    </div>
  )
}

function ErrorBox({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="rounded-md border border-failure/40 bg-failure/10 px-3 py-2 text-sm"
    >
      <p className="text-failure">{text}</p>
      {onRetry ? (
        <button
          type="button"
          className="mt-1 text-xs text-muted-ink underline"
          onClick={onRetry}
        >
          重试
        </button>
      ) : null}
    </div>
  )
}

type ConnAction = "edit" | "discover" | "clear" | "delete"

export function ModelsSection() {
  const qc = useQueryClient()
  const access = useModelsAccess()
  const presets = useModelProviders()
  const connsQ = useModelConnections()
  const catalog = useModelsCatalog()
  const conns = connsQ.data?.connections ?? []
  const models = (catalog.data?.models ?? []).filter((model) => model.source !== "platform")
  const catalogDefaultRef = catalog.data?.default_model_ref ?? null
  const defaultRef = models.some((model) => model.model_ref === catalogDefaultRef)
    ? catalogDefaultRef
    : null

  const [formOpen, setFormOpen] = useState<
    { mode: "add" } | { mode: "edit"; connection: ModelConnection } | null
  >(null)
  const [discoverFor, setDiscoverFor] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<
    | { kind: "delete-conn"; connection: ModelConnection }
    | { kind: "clear-key"; connection: ModelConnection }
    | { kind: "delete-model"; model: ModelItem }
    | null
  >(null)

  const invalidate = () => invalidateModelQueries(qc)

  const onAction = (kind: ConnAction, conn: ModelConnection) => {
    if (kind === "edit") {
      setFormOpen({ mode: "edit", connection: conn })
    } else if (kind === "discover") {
      setDiscoverFor((current) => (current === conn.id ? null : conn.id))
    } else if (kind === "delete") {
      setConfirm({ kind: "delete-conn", connection: conn })
    } else if (kind === "clear") {
      setConfirm({ kind: "clear-key", connection: conn })
    }
  }

  const refreshDisabled = !(
    connsQ.isSuccess &&
    catalog.isSuccess &&
    presets.isSuccess &&
    access.isSuccess
  )
  const refreshAll = () => {
    invalidateModelQueries(qc)
    void qc.invalidateQueries({ queryKey: ["modelProviders"] })
  }

  const mutating = useMutation({
    mutationFn: async () => {
      if (!confirm) return
      if (confirm.kind === "delete-conn") {
        await api.deleteModelConnection(confirm.connection.id)
      } else if (confirm.kind === "clear-key") {
        await api.clearModelConnectionKey(confirm.connection.id)
      } else {
        await api.deleteModel(confirm.model.model_ref)
      }
    },
    onSuccess: () => {
      invalidate()
      setConfirm(null)
    },
  })

  const confirmText =
    confirm?.kind === "delete-conn"
      ? `删除连接“${confirm.connection.display_name}”会同时移除其 ${confirm.connection.model_count} 个已添加模型，引用这些模型的任务将无法运行。`
      : confirm?.kind === "clear-key"
        ? `清除“${confirm.connection.display_name}”的 API Key 后，该连接的模型立即不可用，直到重新填入有效 Key。`
        : confirm?.kind === "delete-model"
          ? `删除模型“${confirm.model.model_id}”后无法再选择它运行任务。`
          : ""
  const confirmLabel = confirm?.kind === "clear-key" ? "清除 Key" : "删除"

  // byok_available=false = 服务端密钥环不可用 → BYOK 整体不可用；
  // require_byok=true 且零连接 → 当前账号尚未配置自有模型。
  const needsConfig =
    access.data?.require_byok === true &&
    access.data.byok_available === true &&
    connsQ.isSuccess &&
    conns.length === 0

  return (
    <div className="space-y-4">
      {access.isPending ? <SkeletonRows /> : null}
      {access.isError ? (
        <ErrorBox
          text={errorWithCode(access.error)}
          onRetry={() => void access.refetch()}
        />
      ) : null}
      {access.data && !access.data.byok_available ? (
        <div className="rounded-lg border border-border bg-card p-4 text-sm">
          <p className="font-medium">自有模型暂不可用</p>
          <p className="mt-1 text-xs text-muted">
            服务端密钥环未就绪，暂时无法接入自有 OpenAI 兼容服务。
          </p>
        </div>
      ) : null}
      {needsConfig ? (
        <div className="rounded-lg border border-waiting/40 bg-waiting/10 p-4 text-sm">
          <p className="font-medium">当前部署需要接入自有模型</p>
          <p className="mt-1 text-xs text-muted">
            点击下方“添加连接”接入你的 OpenAI 兼容服务后即可选择模型。
          </p>
        </div>
      ) : null}

      <Card
        title="模型连接"
        action={
          <span className="flex items-center gap-2">
            <button
              type="button"
              aria-label="刷新模型设置"
              title="刷新"
              disabled={refreshDisabled}
              className="rounded-md p-1.5 text-muted hover:bg-sidebar disabled:opacity-50"
              onClick={refreshAll}
            >
              <IconRefresh size={14} />
            </button>
            {access.data?.byok_available ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setFormOpen({ mode: "add" })}
              >
                <IconPlus size={14} className="mr-1" />
                添加连接
              </Button>
            ) : null}
          </span>
        }
      >
        {connsQ.isPending ? <SkeletonRows /> : null}
        {connsQ.isError ? (
          <ErrorBox
            text={errorWithCode(connsQ.error)}
            onRetry={() => void connsQ.refetch()}
          />
        ) : null}
        {connsQ.isSuccess && conns.length === 0 ? (
          <p className="text-sm text-muted">
            还没有模型连接。添加一个 OpenAI 兼容服务的连接即可选择自有模型。
          </p>
        ) : null}
        {connsQ.isSuccess && conns.length > 0 ? (
          <>
            <table className="hidden w-full text-left text-xs sm:table">
              <thead>
                <tr className="border-b border-border text-muted">
                  <th className="py-2 pr-2 font-medium">连接</th>
                  <th className="py-2 pr-2 font-medium">服务商 / 地址</th>
                  <th className="py-2 pr-2 font-medium">Key 状态</th>
                  <th className="py-2 pr-2 font-medium">连接状态</th>
                  <th className="py-2 pr-2 font-medium">测试状态</th>
                  <th className="py-2 pr-2 font-medium">模型数</th>
                  <th className="py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {conns.map((conn) => (
                  <ConnectionRow
                    key={conn.id}
                    conn={conn}
                    onAction={(kind) => onAction(kind, conn)}
                  />
                ))}
              </tbody>
            </table>
            <ul className="space-y-3 sm:hidden">
              {conns.map((conn) => (
                <li key={conn.id}>
                  <ConnectionCard
                    conn={conn}
                    onAction={(kind) => onAction(kind, conn)}
                  />
                </li>
              ))}
            </ul>
            {discoverFor
              ? (() => {
                  const target = conns.find((c) => c.id === discoverFor)
                  return target ? (
                    <DiscoverLoader
                      connection={target}
                      onChanged={invalidate}
                      onClose={() => setDiscoverFor(null)}
                    />
                  ) : null
                })()
              : null}
          </>
        ) : null}
      </Card>

      <ModelCatalogCard
        pending={catalog.isPending}
        error={catalog.isError ? errorWithCode(catalog.error) : ""}
        onRetry={() => void catalog.refetch()}
        models={models}
        defaultRef={defaultRef}
        onDeleteModel={(model) => setConfirm({ kind: "delete-model", model })}
        onChanged={invalidate}
      />

      {formOpen ? (
        <ConnectionFormDialog
          connection={formOpen.mode === "edit" ? formOpen.connection : null}
          presets={presets.data?.providers ?? []}
          onClose={() => setFormOpen(null)}
          onSaved={invalidate}
        />
      ) : null}
      {confirm ? (
        <ConfirmDialog
          title={
            confirm.kind === "delete-conn"
              ? "删除连接"
              : confirm.kind === "clear-key"
                ? "清除 API Key"
                : "删除模型"
          }
          body={confirmText}
          confirmLabel={confirmLabel}
          danger
          busy={mutating.isPending}
          onClose={() => {
            mutating.reset()
            setConfirm(null)
          }}
          onConfirm={() => {
            void mutating.mutateAsync()
          }}
        />
      ) : null}
      {mutating.isError ? (
        <div className="fixed inset-x-4 bottom-4 z-50 sm:left-auto sm:right-4 sm:w-96">
          <ErrorBox
            text={errorWithCode(mutating.error)}
            onRetry={() => mutating.reset()}
          />
        </div>
      ) : null}
    </div>
  )
}

// 测试连接的显式状态（MOD-12～14）：裸点击 = 免费 catalog 测试，
// 传 model_id = 计费探测（必须先勾选确认）。
function useConnectionTest(connectionId: string) {
  const [result, setResult] = useState<ConnectionTestResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const run = async (modelId?: string) => {
    if (busy) return
    setBusy(true)
    setError("")
    try {
      const res = await api.testModelConnection(connectionId, {
        model_id: modelId,
        allow_billable: Boolean(modelId),
      })
      setResult(res)
    } catch (err) {
      setError(errorWithCode(err))
    } finally {
      setBusy(false)
    }
  }
  return { result, busy, error, run }
}

function StatusChip({ text, tone }: { text: string; tone: string }) {
  return (
    <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${tone}`}>{text}</span>
  )
}

function ConnectionActions({
  test,
  onAction,
}: {
  test: ReturnType<typeof useConnectionTest>
  onAction: (kind: ConnAction) => void
}) {
  const link = "text-xs text-muted-ink underline disabled:opacity-50"
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <button type="button" className={link} onClick={() => onAction("edit")}>
        编辑
      </button>
      <button type="button" className={link} onClick={() => onAction("discover")}>
        拉取模型
      </button>
      <button
        type="button"
        className={link}
        disabled={test.busy}
        // MOD-12：裸“测试连接”= 免费 catalog 测试（不传 model_id）。
        onClick={() => void test.run()}
      >
        {test.busy ? "测试中…" : "测试连接"}
      </button>
      <button type="button" className={link} onClick={() => onAction("clear")}>
        清除 Key
      </button>
      <button
        type="button"
        className={link + " text-failure"}
        onClick={() => onAction("delete")}
      >
        删除
      </button>
    </span>
  )
}

function TestLine({
  conn,
  test,
}: {
  conn: ModelConnection
  test: ReturnType<typeof useConnectionTest>
}) {
  if (!test.result && !test.error) {
    return (
      <span className="text-xs text-muted">
        {TEST_STATUS_TEXT[conn.test_status] ?? conn.test_status}
        {conn.test_status === "failed" && conn.test_error
          ? `：${conn.test_error}`
          : ""}
      </span>
    )
  }
  if (test.error) {
    return (
      <span role="alert" className="block text-xs text-failure">
        {test.error}
      </span>
    )
  }
  const r = test.result!
  return (
    <span className="block text-xs">
      <span className={r.success ? "text-success-ink" : "text-failure"}>
        {r.success ? "通过" : "失败"}
      </span>
      <span className="text-muted">
        {r.model_id ? " · 计费测试" : " · 目录测试"}
        {r.elapsed != null ? ` · ${r.elapsed}s` : ""}
      </span>
      {r.error ? (
        <span className="block text-failure">
          {r.error}
          {r.error_code ? `（${r.error_code}）` : ""}
        </span>
      ) : null}
    </span>
  )
}

function ConnectionStateChip({ conn }: { conn: ModelConnection }) {
  const text = CONN_STATE_TEXT[conn.state] ?? conn.state
  const tone =
    conn.state === "active" ? "bg-success/15 text-success-ink" : "bg-border text-muted-ink"
  return <StatusChip text={text} tone={tone} />
}

function ConnectionRow({
  conn,
  onAction,
}: {
  conn: ModelConnection
  onAction: (kind: ConnAction) => void
}) {
  const test = useConnectionTest(conn.id)
  return (
    <tr className="border-b border-border/60">
      <td className="py-2 pr-2">
        <p className="font-medium text-foreground">{conn.display_name}</p>
        <p className="text-muted">凭据 v{conn.credential_version}</p>
      </td>
      <td className="py-2 pr-2">
        <p>{conn.provider_name}</p>
        <p
          className="max-w-40 truncate font-mono text-[10px] text-muted"
          title={conn.base_url}
        >
          {conn.base_url}
        </p>
      </td>
      <td className="py-2 pr-2">{conn.has_key ? "已设置" : "未设置"}</td>
      <td className="py-2 pr-2">
        <ConnectionStateChip conn={conn} />
      </td>
      <td className="py-2 pr-2">
        <TestLine conn={conn} test={test} />
      </td>
      <td className="py-2 pr-2">{conn.model_count}</td>
      <td className="py-2">
        <ConnectionActions test={test} onAction={onAction} />
      </td>
    </tr>
  )
}

function ConnectionCard({
  conn,
  onAction,
}: {
  conn: ModelConnection
  onAction: (kind: ConnAction) => void
}) {
  const test = useConnectionTest(conn.id)
  const field = "text-xs"
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="min-w-0 truncate text-sm font-medium">{conn.display_name}</p>
        <ConnectionStateChip conn={conn} />
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
        <div>
          <dt className="text-[10px] text-muted">服务商</dt>
          <dd className={field}>{conn.provider_name}</dd>
        </div>
        <div>
          <dt className="text-[10px] text-muted">Base URL</dt>
          <dd className={field + " truncate font-mono"} title={conn.base_url}>
            {conn.base_url}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] text-muted">Key 状态</dt>
          <dd className={field}>{conn.has_key ? "已设置" : "未设置"}</dd>
        </div>
        <div>
          <dt className="text-[10px] text-muted">凭据版本</dt>
          <dd className={field}>v{conn.credential_version}</dd>
        </div>
        <div>
          <dt className="text-[10px] text-muted">测试状态</dt>
          <dd className={field}>
            <TestLine conn={conn} test={test} />
          </dd>
        </div>
        <div>
          <dt className="text-[10px] text-muted">模型数</dt>
          <dd className={field}>{conn.model_count}</dd>
        </div>
      </dl>
      <div className="mt-2 border-t border-border/60 pt-2">
        <ConnectionActions test={test} onAction={onAction} />
      </div>
    </div>
  )
}

// 独立小块：展开时拉取一次 discover 结果并缓存到本地，可重试。
function DiscoverLoader({
  connection,
  onChanged,
  onClose,
}: {
  connection: ModelConnection
  onChanged: () => void
  onClose: () => void
}) {
  const [result, setResult] = useState<DiscoverResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const run = async () => {
    if (busy) return
    setBusy(true)
    setError("")
    try {
      const res = await api.discoverConnectionModels(connection.id)
      setResult(res)
    } catch (err) {
      setError(errorWithCode(err))
    } finally {
      setBusy(false)
    }
  }
  // 首次挂载即拉取（StrictMode dev 会双挂，discover 为只读幂等可接受）。
  useEffect(() => {
    void run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="mt-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted">连接：{connection.display_name}</p>
        <button
          type="button"
          className="text-xs text-muted-ink underline"
          onClick={onClose}
        >
          收起
        </button>
      </div>
      <DiscoverPanel
        connection={connection}
        result={result}
        busy={busy}
        fetchError={error}
        onRetry={() => void run()}
        onChanged={onChanged}
      />
    </div>
  )
}

function ModelCatalogCard({
  pending,
  error,
  onRetry,
  models,
  defaultRef,
  onDeleteModel,
  onChanged,
}: {
  pending: boolean
  error: string
  onRetry: () => void
  models: ModelItem[]
  defaultRef: string | null
  onDeleteModel: (model: ModelItem) => void
  onChanged: () => void
}) {
  const [busyRef, setBusyRef] = useState<string | null>(null)
  const [err, setErr] = useState("")
  const setDefault = async (model: ModelItem) => {
    if (busyRef) return
    setBusyRef(model.model_ref)
    setErr("")
    try {
      await api.setDefaultModel(model.model_ref)
      onChanged()
    } catch (e) {
      setErr(errorWithCode(e))
    } finally {
      setBusyRef(null)
    }
  }

  return (
    <Card title="模型目录">
      {pending ? <SkeletonRows /> : null}
      {error ? <ErrorBox text={error} onRetry={onRetry} /> : null}
      {err ? (
        <div className="mb-2">
          <ErrorBox text={err} onRetry={() => setErr("")} />
        </div>
      ) : null}
      {!pending && !error && models.length === 0 ? (
        <p className="text-sm text-muted">
          目录为空。添加连接后点“拉取模型”，或在连接上手动添加模型 ID。
        </p>
      ) : null}
      {models.length > 0 ? (
        <ul className="divide-y divide-border/60">
          {models.map((model) => (
            <ModelRow
              key={model.model_ref}
              model={model}
              isDefault={model.model_ref === defaultRef}
              busy={busyRef === model.model_ref}
              onDefault={() => void setDefault(model)}
              onDelete={() => onDeleteModel(model)}
              onChanged={onChanged}
            />
          ))}
        </ul>
      ) : null}
    </Card>
  )
}

function ModelRow({
  model,
  isDefault,
  busy,
  onDefault,
  onDelete,
  onChanged,
}: {
  model: ModelItem
  isDefault: boolean
  busy: boolean
  onDefault: () => void
  onDelete: () => void
  onChanged: () => void
}) {
  const [testBusy, setTestBusy] = useState(false)
  const [testRes, setTestRes] = useState<ConnectionTestResult | null>(null)
  const [testErr, setTestErr] = useState("")
  const [confirmBillable, setConfirmBillable] = useState(false)
  const isPlatform = model.source === "platform"

  // MOD-13：计费探测每次都要重新勾选确认（一次性）。
  const runBillableTest = async () => {
    if (!confirmBillable || testBusy || isPlatform) return
    setTestBusy(true)
    setTestErr("")
    setTestRes(null)
    try {
      const res = await api.testModelConnection(model.connection_id, {
        model_id: model.model_id,
        allow_billable: true,
      })
      setTestRes(res)
      onChanged()
    } catch (err) {
      setTestErr(errorWithCode(err))
    } finally {
      setTestBusy(false)
      setConfirmBillable(false)
    }
  }

  return (
    <li className="py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-label={isDefault ? "当前默认模型" : "设为默认模型"}
          title={isDefault ? "当前默认模型" : "设为默认模型"}
          disabled={busy}
          className="shrink-0 rounded p-1 disabled:opacity-50"
          onClick={onDefault}
        >
          <IconStar
            size={16}
            fill={isDefault ? "currentColor" : "none"}
            className={isDefault ? "text-waiting-ink" : "text-muted"}
          />
        </button>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm">
            {model.display_name || model.model_id}
            {isDefault ? (
              <span className="ml-2 rounded-full bg-waiting/15 px-1.5 py-0.5 text-[10px] text-waiting-ink">
                默认
              </span>
            ) : null}
          </span>
          <span className="text-xs text-muted">
            {model.connection_name || model.provider_name}
            {" · "}
            {MODEL_STATUS_TEXT[model.status] ?? model.status}
            {" · "}
            <span className="font-mono">{model.model_id}</span>
          </span>
        </span>
        {isPlatform ? null : (
          <button
            type="button"
            aria-label={`删除模型 ${model.model_id}`}
            title="删除模型"
            className="shrink-0 rounded p-1.5 text-muted hover:bg-sidebar hover:text-failure"
            onClick={onDelete}
          >
            <IconTrash size={14} />
          </button>
        )}
      </div>
      {!isPlatform ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 pl-8">
          <label className="rxy-billable-confirm flex cursor-pointer items-center gap-1.5 text-xs text-muted-ink">
            <input
              type="checkbox"
              checked={confirmBillable}
              disabled={testBusy}
              onChange={(event) => setConfirmBillable(event.target.checked)}
            />
            我已知晓这会发起一次真实计费请求
          </label>
          <button
            type="button"
            className="text-xs text-muted-ink underline disabled:opacity-50"
            disabled={!confirmBillable || testBusy}
            title={
              !confirmBillable
                ? "先勾选确认会发起真实计费请求"
                : "发起一次真实模型调用"
            }
            onClick={() => void runBillableTest()}
          >
            {testBusy ? "测试中…" : "测试此模型"}
          </button>
          {testBusy ? <IconSpinner size={12} className="text-muted" /> : null}
          {testRes ? (
            <span
              className={
                testRes.success
                  ? "text-xs text-success-ink"
                  : "text-xs text-failure"
              }
            >
              {testRes.success ? "通过" : "失败"}
              {testRes.elapsed != null ? ` · ${testRes.elapsed}s` : ""}
              {testRes.error ? `：${testRes.error}` : ""}
            </span>
          ) : null}
          {testErr ? (
            <span role="alert" className="text-xs text-failure">
              {testErr}
            </span>
          ) : null}
        </div>
      ) : null}
    </li>
  )
}
