/** UPDATE-01 轨 I: /effort overlay helpers. Do not fold Default into DialogEffort.buildOptions. */

export const SELECT_EFFORT_TITLE = "Select effort";
export const DEFAULT_EFFORT_VALUE = "default";
/** OpenCode-style gold chip next to the model name. */
export const EFFORT_CHIP_FG = "#f9e2af";

export type EffortPickerOption = {
  id: string;
  title: string;
  description?: string;
  value: string;
};

export function shouldOpenEffortPicker(
  effortOptions: readonly string[] | null | undefined,
): boolean {
  return (
    Array.isArray(effortOptions) &&
    effortOptions.some((item) => String(item).trim().length > 0)
  );
}

export function planAfterModelSwitch(
  effortOptions: readonly string[] | null | undefined,
): "effort" | "close" {
  return shouldOpenEffortPicker(effortOptions) ? "effort" : "close";
}

export function formatComposerEffortChip(
  effort: string | null | undefined,
): string {
  const value = String(effort || "").trim();
  return value || DEFAULT_EFFORT_VALUE;
}

export function buildEffortPickerOptions(
  vendorOptions: EffortPickerOption[],
): EffortPickerOption[] {
  return [
    {
      id: DEFAULT_EFFORT_VALUE,
      title: "Default",
      description: "使用当前模型的默认思考强度",
      value: DEFAULT_EFFORT_VALUE,
    },
    ...vendorOptions,
  ];
}
