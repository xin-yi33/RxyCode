import { type DialogSelectOption } from "./DialogSelect.tsx";
import { type ModelInfo } from "./api.ts";

/**
 * OpenCode-style /model list:
 * - Every model stays under its provider group (DeepSeek / OpenCode Go / 其他…)
 * - Recent switches are *also* listed under 最近常用 (duplicates, same value id)
 * - Display title = nickname || vendor model id (not namespaced config key)
 */
function modelDisplayTitle(m: ModelInfo, collide: boolean): string {
  const base = m.nickname || m.provider_model_id || m.name || m.id;
  if (!collide) return base;
  const provider = m.category || m.provider_name || "";
  const host = (() => {
    try {
      return m.base_url ? new URL(m.base_url).host : "";
    } catch {
      return "";
    }
  })();
  const tag = host || provider;
  return tag && !base.includes(tag) ? `${base} · ${tag}` : base;
}

export function buildModelListOptions(
  models: ModelInfo[],
  recent: string[],
  active: string,
): { options: DialogSelectOption<string>[]; categoryOrder: string[] } {
  const recentIds = recent;
  const providerNames = new Set<string>();
  const opts: DialogSelectOption<string>[] = [];
  const titleCount = new Map<string, number>();
  for (const m of models) {
    const base = m.nickname || m.provider_model_id || m.name || m.id;
    titleCount.set(base, (titleCount.get(base) || 0) + 1);
  }

  for (const m of models) {
    const provider =
      m.category || m.provider_name || "其他";
    if (provider !== "其他") {
      providerNames.add(provider);
    }
    const rawTitle = m.nickname || m.provider_model_id || m.name || m.id;
    const title = modelDisplayTitle(m, (titleCount.get(rawTitle) || 0) > 1);
    const vendor = m.provider_model_id || m.name || "";
    const host = (() => {
      try {
        return m.base_url ? new URL(m.base_url).host : "";
      } catch {
        return "";
      }
    })();
    // Phase 3 M6：显示输出上限摘要（来源 + 解析值），缺失时静默省略。
    const limit = modelLimitSummary(m);
    const description = [provider, vendor !== title ? vendor : "", host, limit]
      .filter(Boolean)
      .join(" · ");
    const footer = m.active || m.id === active
      ? (host ? `当前 · ${host}` : "当前")
      : host || m.base_url || "";

    opts.push({
      id: m.id,
      title,
      description,
      footer,
      category: provider,
      value: m.id,
    });
  }

  // Duplicate recent models at top (OpenCode-like quick access), same switch id.
  for (const recentId of recentIds) {
    const m = models.find((item) => item.id === recentId);
    if (!m) continue;
    const provider = m.category || m.provider_name || "其他";
    const rawTitle = m.nickname || m.provider_model_id || m.name || m.id;
    const title = modelDisplayTitle(m, (titleCount.get(rawTitle) || 0) > 1);
    const host = (() => {
      try {
        return m.base_url ? new URL(m.base_url).host : "";
      } catch {
        return "";
      }
    })();
    opts.unshift({
      id: `recent:${m.id}`,
      title,
      description: [provider, host].filter(Boolean).join(" · "),
      footer: m.active || m.id === active
        ? (host ? `当前 · ${host}` : "当前")
        : host || "",
      category: "最近常用",
      value: m.id,
    });
  }

  opts.push({
    id: "__add__",
    title: "+ 添加模型",
    description: "打开添加向导",
    category: "操作",
    value: "__add__",
  });

  const categoryOrder = [
    "最近常用",
    ...[...providerNames].sort((a, b) => a.localeCompare(b)),
    "其他",
    "操作",
  ];

  return { options: opts, categoryOrder };
}

/**
 * Phase 3 M6：把模型输出上限摘要渲染成一行文本（缺失时返回空串）。
 *
 * - 明确"未知模型兜底"≠"官方上限"：limit_source=unknown_fallback 时标注 "兜底"。
 * - 旧服务器缺失摘要字段时返回 ""（前端不自行计算/不猜模型族）。
 */
export function modelLimitSummary(m: ModelInfo): string {
  const value = m.resolved_max_tokens;
  const source = m.limit_source;
  if (typeof value !== "number" || value <= 0 || !source) {
    return "";
  }
  const sourceLabel: Record<string, string> = {
    explicit_config: "显式",
    catalog_exact_provider: "目录",
    catalog_exact_model: "目录",
    catalog_family: "目录族",
    provider_default: "服务商默认",
    unknown_fallback: "兜底",
    context_cap: "上下文钳制",
    explicit_clamped: "显式钳制",
    legacy_server: "旧服务",
  };
  const label = sourceLabel[source] || source;
  return `输出${label} ${value}`;
}
