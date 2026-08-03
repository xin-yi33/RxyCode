import { useCallback, useEffect, useState } from "react";
import { DialogSelect } from "./DialogSelect.tsx";
import { fetchModels, sendCommand } from "./api.ts";
import { buildModelListOptions } from "./DialogModel.options.ts";
import {
  interpretModelSwitchResult,
  modelSwitchCommand,
} from "./dialogModelFlow.ts";

export { buildModelListOptions } from "./DialogModel.options.ts";

async function loadModelDialogState(activeModel?: string) {
  const result = await fetchModels();
  if (!result.ok) {
    return {
      ok: false as const,
      error: result.error || "无法加载模型列表",
      options: [] as ReturnType<typeof buildModelListOptions>["options"],
      categoryOrder: [] as string[],
      current: activeModel || "",
    };
  }
  const built = buildModelListOptions(result.models, result.recent, result.active);
  return {
    ok: true as const,
    error: "",
    options: built.options,
    categoryOrder: built.categoryOrder,
    current: result.active || activeModel || "",
  };
}

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
  const [loadError, setLoadError] = useState("");
  const [switchError, setSwitchError] = useState("");
  const [switching, setSwitching] = useState(false);

  const refreshModels = useCallback(async () => {
    const state = await loadModelDialogState(activeModel);
    if (!state.ok) {
      setLoadError(state.error);
      setOptions([]);
      setCategoryOrder([]);
      return;
    }
    setLoadError("");
    setCurrent(state.current);
    setOptions(state.options);
    setCategoryOrder(state.categoryOrder);
  }, [activeModel]);

  useEffect(() => {
    void refreshModels();
  }, [refreshModels]);

  const footerHint = switching
    ? "正在切换模型..."
    : switchError
      ? `切换失败: ${switchError}`
      : loadError
        ? `加载失败: ${loadError}`
        : undefined;

  return (
    <DialogSelect
      title="选择模型"
      options={options}
      categoryOrder={categoryOrder}
      placeholder="搜索模型"
      currentId={current}
      onClose={onClose}
      footerHint={footerHint}
      onSelect={(opt) => {
        if (opt.value === "__add__") {
          onSwitched("__add__", "");
          return;
        }
        if (switching) return;
        void (async () => {
          setSwitching(true);
          setSwitchError("");
          const result = await sendCommand(modelSwitchCommand(opt.value));
          const outcome = interpretModelSwitchResult(opt.value, result);
          setSwitching(false);
          if (!outcome.ok) {
            setSwitchError(outcome.error);
            await refreshModels();
            return;
          }
          setCurrent(opt.value);
          onSwitched(outcome.modelId, outcome.message);
          onClose();
        })();
      }}
    />
  );
}
