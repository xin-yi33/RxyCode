/**
 * OpenTUI color tokens.
 *
 * Base surfaces are a near-black #0f1115 family — never pure #000.  A true
 * black canvas makes the composer frame and panels disappear into the bezel
 * on OLED / dimmed terminals (users reported "看不出输入框边界"), so the app
 * canvas, panels/cards, the raised rows and the composer field all come from
 * SURFACES with a deliberate one-step luminance hierarchy.
 *
 * Raw surface hex values live here only; C re-exports them so existing call
 * sites keep working, and uiPolish.test.tsx locks the non-pure-black rule.
 */

export const SURFACES = {
  /** App canvas — near-black, never #000. */
  app: "#0f1115",
  /** Panels / cards (dialogs, plan pane, command suggestions). */
  surface0: "#151922",
  /** Raised rows and selected rows inside a panel. */
  surface1: "#1b2029",
  /** User bubble / panel field. */
  userBubble: "#171b23",
  /** Composer shell field — one shell, one step above the canvas. */
  field: "#12161d",
  /** Scrollbar track inside panels. */
  track: "#151922",
} as const;

export type SurfaceToken = keyof typeof SURFACES;
export const SURFACE_KEYS = Object.keys(SURFACES) as SurfaceToken[];

/** True for #000 / #000000 (and short form), case-insensitive. */
export function isPureBlack(hex: string): boolean {
  const value = String(hex ?? "").trim().toLowerCase().replace(/^#/, "");
  if (!/^[0-9a-f]{3}$/.test(value) && !/^[0-9a-f]{6}$/.test(value)) return false;
  const full = value.length === 3
    ? value.split("").map((ch) => ch + ch).join("")
    : value;
  return full === "000000";
}

/** Relative luminance (WCAG) — used to assert the surface hierarchy is ordered. */
export function relativeLuminance(hex: string): number {
  const value = String(hex ?? "").trim().replace(/^#/, "").toLowerCase();
  const full = value.length === 3
    ? value.split("").map((ch) => ch + ch).join("")
    : value;
  if (!/^[0-9a-f]{6}$/.test(full)) return Number.NaN;
  const channel = (offset: number) => {
    const srgb = Number.parseInt(full.slice(offset, offset + 2), 16) / 255;
    return srgb <= 0.03928 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4);
}

/** True-black + classic Ink pinks (match original RxyCode screenshot). */
export const C = {
  bg: SURFACES.app,
  surface0: SURFACES.surface0,
  surface1: SURFACES.surface1,
  /** OpenCode-style user/panel field — one step above the canvas. */
  userBubble: SURFACES.userBubble,
  /** Composer shell field (single-shell input area). */
  field: SURFACES.field,
  /** Panel cards and dialog chrome. */
  panel: SURFACES.surface0,
  overlay2: "#555555",
  subtext: "#aaaaaa",
  text: "#ffffff",
  primary: "#FF69B4",
  accent: "#FFB6C1",
  mauve: "#cba6f7",
  green: "#a6e3a1",
  red: "#f38ba8",
  diffAddBg: "#1a4a32",
  diffDelBg: "#6b3038",
  teal: "#94e2d5",
  yellow: "#f9e2af",
  border: "#FF69B4",
  borderDim: "#333333",
  brandLight: "#FFB6C1",
  brandHot: "#FF69B4",
  thinking: "#FFD700",
} as const;
