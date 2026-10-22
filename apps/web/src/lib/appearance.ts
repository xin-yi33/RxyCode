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
]

export type ResolvedAppearance = {
  mode: "light" | "dark"
  profile: AppearanceProfile
  reducedMotion: boolean
  diffMarkers: "color" | "symbols"
  uiFontPx: number
  codeFontPx: number
  contrast: "normal" | "high"
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
    contrast: profile.contrast ?? "normal",
  }
}

export function applyAppearance(resolved: ResolvedAppearance): void {
  if (typeof document === "undefined") return
  const root = document.documentElement
  root.classList.toggle("dark", resolved.mode === "dark")
  root.dataset.theme = resolved.mode
  root.dataset.contrast = resolved.contrast
  root.dataset.diffMarkers = resolved.diffMarkers
  root.style.setProperty("--rxy-ui-font", `${resolved.uiFontPx}px`)
  root.style.setProperty("--rxy-code-font", `${resolved.codeFontPx}px`)
  root.style.fontSize = `${resolved.uiFontPx}px`
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
