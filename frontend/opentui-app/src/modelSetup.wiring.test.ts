import { describe, expect, test } from "bun:test";
import { welcomeRowsForSetup, WELCOME_ROWS } from "./brand.ts";
import { decideModelSetup, NO_MODEL_WELCOME_HINT } from "./modelSetup.ts";

describe("model setup wiring", () => {
  test("welcomeRowsForSetup appends hint only when needed", () => {
    const withHint = welcomeRowsForSetup(true);
    const without = welcomeRowsForSetup(false);
    expect(
      withHint.some((r) => r.parts.some((p) => p.text.includes(NO_MODEL_WELCOME_HINT))),
    ).toBe(true);
    expect(
      without.some((r) => r.parts.some((p) => p.text.includes(NO_MODEL_WELCOME_HINT))),
    ).toBe(false);
    expect(without.length).toBe(WELCOME_ROWS.length);
    expect(withHint.length).toBe(WELCOME_ROWS.length + 1);
  });

  test("decideModelSetup re-exported for App probe wiring", () => {
    expect(decideModelSetup({ fetchOk: false, modelCount: 0, alreadyAutoOpened: false })).toEqual({
      needsSetup: false,
      shouldAutoOpen: false,
    });
    expect(decideModelSetup({ fetchOk: true, modelCount: 0, alreadyAutoOpened: false })).toEqual({
      needsSetup: true,
      shouldAutoOpen: true,
    });
    expect(NO_MODEL_WELCOME_HINT).toBe("尚未配置模型 — 输入 /addmodel 或按 Ctrl+P");
  });
});
