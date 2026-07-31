import { useEffect, useState } from "react";
import { DialogSelect } from "./DialogSelect.tsx";
import { fetchModels, sendCommand } from "./api.ts";
import { buildModelListOptions } from "./DialogModel.options.ts";

export { buildModelListOptions } from "./DialogModel.options.ts";

export function DialogModel({
  onClose,
  onSwitched,
  activeModel,
}: {
  onClose: () => void;
  onSwitched: (modelId: string, message: string) => void;
  activeModel?: string;
}) {
  const [options, setOptions] = useState<ReturnType<typeof buildModelListOptions>["options"]>([]);
  const [categoryOrder, setCategoryOrder] = useState<string[]>([]);
  const [current, setCurrent] = useState(activeModel || "");

  useEffect(() => {
    void (async () => {
      const { models, active, recent } = await fetchModels();
      setCurrent(active || activeModel || "");
      const built = buildModelListOptions(models, recent, active);
      setOptions(built.options);
      setCategoryOrder(built.categoryOrder);
    })();
  }, [activeModel]);

  return (
    <DialogSelect
      title="选择模型"
      options={options}
      categoryOrder={categoryOrder}
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
