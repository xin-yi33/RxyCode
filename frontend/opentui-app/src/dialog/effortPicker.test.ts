import { describe, expect, test } from "bun:test";
import {
  DEFAULT_EFFORT_VALUE,
  SELECT_EFFORT_TITLE,
  buildEffortPickerOptions,
  formatComposerEffortChip,
  planAfterModelSwitch,
  shouldOpenEffortPicker,
} from "./effortPicker.ts";

describe("effort picker routing", () => {
  test("title stays Select effort", () => {
    expect(SELECT_EFFORT_TITLE).toBe("Select effort");
  });

  test("opens after /model when the model has vendor gears", () => {
    expect(shouldOpenEffortPicker(["low", "high", "max"])).toBe(true);
    expect(planAfterModelSwitch(["max"])).toBe("effort");
  });

  test("does not open when the model has no gears", () => {
    expect(shouldOpenEffortPicker([])).toBe(false);
    expect(shouldOpenEffortPicker(undefined)).toBe(false);
    expect(planAfterModelSwitch([])).toBe("close");
  });

  test("Default is prepended and is not mixed into vendor rows", () => {
    const rows = buildEffortPickerOptions([
      { id: "max", title: "max", value: "max" },
    ]);
    expect(rows[0]).toEqual({
      id: DEFAULT_EFFORT_VALUE,
      title: "Default",
      description: "使用当前模型的默认思考强度",
      value: DEFAULT_EFFORT_VALUE,
    });
    expect(rows.map((row) => row.value)).toEqual(["default", "max"]);
  });

  test("composer chip shows the live gear or default", () => {
    expect(formatComposerEffortChip("max")).toBe("max");
    expect(formatComposerEffortChip("high")).toBe("high");
    expect(formatComposerEffortChip(null)).toBe("default");
    expect(formatComposerEffortChip("")).toBe("default");
  });
});
