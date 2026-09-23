/**
 * DialogEffort — 选择思考强度（/effort 命令）。
 *
 * 照抄 DialogModel 模式（OpenCode 风格）：选项 = 当前模型的厂商档位全集
 * （models/list 的 effort_options，英文档位名 low/medium/high/max 等，
 * 档位随当前模型动态变化）；当前档位 footer 标记；上下键 + 回车确认。
 * 模型无档位（effort_options 空）→ 显示"当前模型不支持档位选择"。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { DialogSelect } from "./DialogSelect.tsx";
import { sendCommand } from "../chatApi.ts";
import { fetchEffortOptions, type ModelInfo } from "./api.ts";
import {
  DEFAULT_EFFORT_VALUE,
  SELECT_EFFORT_TITLE,
  buildEffortPickerOptions,
} from "./effortPicker.ts";

/** 档位 → 中文说明（opencode 风格：英文档位 + 中文释义；未知档位保留原文）。 */
export const EFFORT_DESCRIPTIONS: Record<string, string> = {
  low: "较低的思考强度，更快更省",
  medium: "均衡的思考强度（默认）",
  high: "较高的思考强度，更深入推理",
  max: "最高的思考强度，最深入推理",
  xhigh: "极高思考强度",
  minimal: "最小思考强度（几乎不推理）",
  none: "关闭推理",
};

export type EffortOption = {
  id: string;
  title: string;
  description?: string;
  footer?: string;
  category?: string;
  value: string;
  disabled?: boolean;
};

function describe(value: string): string {
  return EFFORT_DESCRIPTIONS[value] ?? "自定义档位";
}

export function buildOptions(models: ModelInfo[], activeId: string): {
  options: EffortOption[];
  modelName: string;
} {
  const activeModel = models.find((m) => m.id === activeId) ?? models[0];
  const modelName = activeModel?.nickname ?? activeModel?.name ?? "";
  const effortOptions = activeModel?.effort_options ?? [];
  return {
    modelName,
    options: effortOptions.map((value) => ({
      id: value,
      title: value,
      description: describe(value),
      value,
    })),
  };
}

export function DialogEffort({
  onClose,
  onChanged,
}: {
  onClose: () => void;
  onChanged: (effort: string, message: string) => void;
}) {
  const [options, setOptions] = useState<EffortOption[]>([]);
  const [current, setCurrent] = useState("");
  const [modelName, setModelName] = useState("");
  const [loadError, setLoadError] = useState("");
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState("");
  const committedRef = useRef(false);

  const refresh = useCallback(async () => {
    const result = await fetchEffortOptions();
    if (!result.ok) {
      setLoadError(result.error || "无法加载模型信息");
      setOptions([]);
      return;
    }
    const built = buildOptions(result.models, result.active);
    setOptions(buildEffortPickerOptions(built.options));
    setModelName(built.modelName);
    setCurrent(result.effort || DEFAULT_EFFORT_VALUE);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const footerHint = switchError
    ? switchError
    : loadError
      ? `加载失败: ${loadError}`
      : options.length === 0
        ? "当前模型不支持档位选择"
        : modelName
          ? `模型 ${modelName} · 当前: ${current || DEFAULT_EFFORT_VALUE}`
          : undefined;

  const dismiss = useCallback(() => {
    if (committedRef.current) {
      onClose();
      return;
    }
    committedRef.current = true;
    void (async () => {
      const result = await sendCommand(`/effort ${DEFAULT_EFFORT_VALUE}`);
      if (result.ok) {
        onChanged(
          DEFAULT_EFFORT_VALUE,
          result.message || `思考强度已切换: ${DEFAULT_EFFORT_VALUE}`,
        );
      }
      onClose();
    })();
  }, [onChanged, onClose]);

  return (
    <DialogSelect
      title={SELECT_EFFORT_TITLE}
      options={options}
      placeholder="搜索档位"
      currentId={current}
      onClose={dismiss}
      footerHint={footerHint}
      onSelect={(opt) => {
        if (switching) return;
        void (async () => {
          setSwitching(true);
          setSwitchError("");
          try {
            const result = await sendCommand(`/effort ${opt.value}`);
            if (!result.ok) {
              setSwitchError(result.error || result.message || "无法连接 API 服务");
              return;
            }
            committedRef.current = true;
            setCurrent(opt.value);
            onChanged(opt.value, result.message || `思考强度已切换: ${opt.value}`);
            onClose();
          } catch (err: unknown) {
            setSwitchError(err instanceof Error ? err.message : "切换失败");
          } finally {
            setSwitching(false);
          }
        })();
      }}
    />
  );
}
