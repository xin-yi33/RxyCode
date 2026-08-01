import { type DialogSelectOption } from "./DialogSelect.tsx";
import { type ModelInfo } from "./api.ts";

/**
 * OpenCode-style /model list:
 * - Every model stays under its provider group (DeepSeek / OpenCode Go / 其他…)
 * - Recent switches are *also* listed under 最近常用 (duplicates, same value id)
 * - Display title = nickname || vendor model id (not namespaced config key)
 */
export function buildModelListOptions(
  models: ModelInfo[],
  recent: string[],
  active: string,
): { options: DialogSelectOption<string>[]; categoryOrder: string[] } {
  const recentIds = recent;
  const providerNames = new Set<string>();
  const opts: DialogSelectOption<string>[] = [];

  for (const m of models) {
    const provider =
      m.category || m.provider_name || "其他";
    if (provider !== "其他") {
      providerNames.add(provider);
    }
    const title = m.nickname || m.provider_model_id || m.name || m.id;
    const description = m.provider_model_id || m.name || "";
    const footer = m.active || m.id === active ? "当前" : m.base_url || "";

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
    opts.unshift({
      id: `recent:${m.id}`,
      title: m.nickname || m.provider_model_id || m.name || m.id,
      description: m.provider_model_id || m.name || "",
      footer: m.active || m.id === active ? "当前" : m.base_url || "",
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
