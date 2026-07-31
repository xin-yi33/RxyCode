import { type DialogSelectOption } from "./DialogSelect.tsx";
import { type ModelInfo } from "./api.ts";

export function buildModelListOptions(
  models: ModelInfo[],
  recent: string[],
  active: string,
): { options: DialogSelectOption<string>[]; categoryOrder: string[] } {
  const recentSet = new Set(recent);
  const providerNames = new Set<string>();

  const opts: DialogSelectOption<string>[] = models.map((m) => {
    const category = recentSet.has(m.id)
      ? "最近常用"
      : m.category || m.provider_name || "其他";
    if (category !== "最近常用" && category !== "其他") {
      providerNames.add(category);
    }
    return {
      id: m.id,
      title: m.nickname || m.name || m.id,
      description: m.provider_model_id || m.name || "",
      footer: m.active || m.id === active ? "当前" : m.base_url || "",
      category,
      value: m.id,
    };
  });

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
