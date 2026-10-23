// The appearance engine: server preferences are the source of truth when
// signed in; the `rxy_theme` cookie keeps first paint right for guests and
// reloads. Everything applies as attributes/classes on <html> so existing
// Tailwind theme tokens keep working.
import type { AppearanceProfile, Preferences } from "../sdk/client"

export type ThemeSpec = {
  id: string
  name: string
  kind: "light" | "dark"
  accent: string
  background: string
  foreground: string
  source: string
  license: string
  version: string
}

// Bundled theme catalogue — no network fetch (API-PREF contract).
export const THEMES: ThemeSpec[] = [
  {
    id: "rxy-light",
    name: "Rxy Light",
    kind: "light",
    accent: "#0f62fe",
    background: "#ffffff",
    foreground: "#1c1c1e",
    source: "bundled",
    license: "MIT",
    version: "1.0.0",
  },
  {
    id: "rxy-dark",
    name: "Rxy Dark",
    kind: "dark",
    accent: "#7aa2ff",
    background: "#111114",
    foreground: "#e7e7ea",
    source: "bundled",
    license: "MIT",
    version: "1.0.0",
  },
  {
    id: "rxy-paper",
    name: "Rxy Paper",
    kind: "light",
    accent: "#b25e09",
    background: "#faf6ef",
    foreground: "#26221c",
    source: "bundled",
    license: "MIT",
    version: "1.0.0",
  },
  {
    id: "rxy-midnight",
    name: "Rxy Midnight",
    kind: "dark",
    accent: "#58a6ff",
    background: "#0b1220",
    foreground: "#dde6f2",
    source: "bundled",
    license: "MIT",
    version: "1.0.0",
  },
]

export const ACCENTS: { id: string; name: string; color: string }[] = [
  { id: "default", name: "默认", color: "" },
  { id: "blue", name: "蓝", color: "#0f62fe" },
  { id: "green", name: "绿", color: "#1a7f37" },
  { id: "orange", name: "橙", color: "#bc4c00" },
  { id: "purple", name: "紫", color: "#8250df" },
  { id: "rose", name: "玫红", color: "#bf3989" },
]

export type ResolvedAppearance = {
  mode: "light" | "dark"
  profile: AppearanceProfile
  reducedMotion: boolean
  diffMarkers: "color" | "symbols"
  uiFontPx: number
  codeFontPx: number
  /** 0–100 视觉差异强度（APP-14）。 */
  contrast: number
}

export function resolveAppearance(
  prefs: Preferences | null | undefined,
): ResolvedAppearance {
  const appearance = prefs?.appearance
  const modeSetting = appearance?.mode ?? "system"
  const systemDark =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-color-scheme: dark)").matches
  const mode = modeSetting === "system" ? (systemDark ? "dark" : "light") : modeSetting
  const separate = appearance?.separate_modes ?? false
  const scoped =
    separate && mode === "light"
      ? appearance?.light
      : separate && mode === "dark"
        ? appearance?.dark
        : null
  const profile = { ...(appearance?.shared ?? {}), ...(scoped ?? {}) }
  const motionPref =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  const reducedMotion =
    appearance?.reduced_motion === "on" ||
    (appearance?.reduced_motion !== "off" && motionPref)
  return {
    mode,
    profile,
    reducedMotion,
    diffMarkers: appearance?.diff_markers ?? "color",
    uiFontPx: profile.ui_font_px ?? 14,
    codeFontPx: profile.code_font_px ?? 13,
    contrast:
      typeof profile.contrast === "number"
        ? Math.max(0, Math.min(100, profile.contrast))
        : profile.contrast === "high"
          ? 80
          : 45,
  }
}

export function applyAppearance(resolved: ResolvedAppearance): void {
  if (typeof document === "undefined") return
  const root = document.documentElement
  root.classList.toggle("dark", resolved.mode === "dark")
  root.dataset.theme = resolved.mode
  // 既有 CSS 按 "high"/"normal" 分档；细粒度数值也落到 CSS 变量。
  root.dataset.contrast = resolved.contrast >= 70 ? "high" : "normal"
  root.style.setProperty("--rxy-contrast", String(resolved.contrast))
  root.dataset.diffMarkers = resolved.diffMarkers
  root.style.setProperty("--rxy-ui-font", `${resolved.uiFontPx}px`)
  root.style.setProperty("--rxy-code-font", `${resolved.codeFontPx}px`)
  root.classList.toggle("reduced-motion", resolved.reducedMotion)
  const { accent, background, foreground, theme_id } = resolved.profile
  if (accent) root.style.setProperty("--rxy-accent", accent)
  if (background) root.style.setProperty("--rxy-bg", background)
  if (foreground) root.style.setProperty("--rxy-fg", foreground)
  root.dataset.themeId = theme_id ?? (resolved.mode === "dark" ? "rxy-dark" : "rxy-light")
  try {
    document.cookie = `rxy_theme=${resolved.mode};path=/;samesite=lax;max-age=31536000`
  } catch {
    // best effort
  }
}
