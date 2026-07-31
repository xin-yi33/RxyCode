import { useEffect, useState } from "react";
import { DialogSelect, type DialogSelectOption } from "./DialogSelect.tsx";
import { fetchModels, sendCommand, type ModelInfo } from "./api.ts";

export function DialogModel({
  onClose,
  onSwitched,
  activeModel,
}: {
  onClose: () => void;
  onSwitched: (modelId: string, message: string) => void;
  activeModel?: string;
}) {
  const [options, setOptions] = useState<DialogSelectOption<string>[]>([]);
  const [current, setCurrent] = useState(activeModel || "");

  useEffect(() => {
    void (async () => {
      const { models, active, recent } = await fetchModels();
      setCurrent(active || activeModel || "");
      // "最近常用" is real switch history from the backend (config.recent_models),
      // never a hard-coded template list.
      const recentSet = new Set(recent);
      const opts: DialogSelectOption<string>[] = models.map((m: ModelInfo) => ({
        id: m.id,
        title: m.nickname || m.name || m.id,
        description: m.provider_model_id || m.name || "",
        footer: m.active || m.id === active ? "当前" : m.base_url || "",
        category: recentSet.has(m.id) ? "最近常用" : "模型",
        value: m.id,
      }));
      opts.push({
        id: "__add__",
        title: "+ 添加模型",
        description: "打开添加向导",
        category: "操作",
        value: "__add__",
      });
      setOptions(opts);
    })();
  }, [activeModel]);

  return (
    <DialogSelect
      title="选择模型"
      options={options}
      categoryOrder={["最近常用", "模型", "操作"]}
      placeholder="搜索模型"
      currentId={current}
      onClose={onClose}
      onSelect={(opt) => {
        if (opt.value === "__add__") {
          onSwitched("__add__", "");
          return;
        }
        void (async () => {
          const result = await sendCommand(`/model ${opt.value}`);
          onSwitched(opt.value, String(result?.message || `已切换: ${opt.value}`));
          onClose();
        })();
      }}
    />
  );
}
