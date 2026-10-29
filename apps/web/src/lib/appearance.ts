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

/** "#rgb"/"#rrggbb" → "r, g, b"（--rxy-accent 的 Tailwind 通道同步）。 */
function hexToRgbChannels(hex: string): string | null {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return null
  let h = m[1]
  if (h.length === 3) h = [...h].map((c) => c + c).join("")
  const n = Number.parseInt(h, 16)
  return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`
}

/** WCAG 相对亮度（0–1），供 accent → ink 反色判定。 */
function relLuminance(hex: string): number | null {
  const rgb = hexToRgbChannels(hex)
  if (!rgb) return null
  const lin = rgb.split(",").map((s) => {
    const v = Number(s) / 255
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
  })
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
}

const ACCENT_INK_LIGHT = "#ffffff"
const ACCENT_INK_DARK = "#212121" // 与暗色 --rxy-bg 一致的深墨

/**
 * 按 accent 亮度挑可读前景墨：默认深蓝 #0f62fe 配白字；亮色 accent
 * （Rxy Dark #7aa2ff / Rxy Midnight #58a6ff 上白字仅 ~2.5:1）配深墨。
 */
export function accentInkFor(accent: string): string {
  const l = relLuminance(accent)
  if (l == null) return ACCENT_INK_LIGHT
  const cLight = 1.05 / (l + 0.05)
  const darkL = relLuminance(ACCENT_INK_DARK)
  const cDark = darkL == null ? 0 : (l + 0.05) / (darkL + 0.05)
  return cLight >= cDark ? ACCENT_INK_LIGHT : ACCENT_INK_DARK
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
  if (accent) {
    root.style.setProperty("--rxy-accent", accent)
    // 与 --rxy-accent 同步，Tailwind accent/30 等透明度修饰只认 -rgb 通道；
    // accent-ink 按 accent 亮度反色（亮色 accent 上白字不达 AA）。
    const rgb = hexToRgbChannels(accent)
    if (rgb) root.style.setProperty("--rxy-accent-rgb", rgb)
    root.style.setProperty("--rxy-accent-ink", accentInkFor(accent))
  } else {
    // “默认”/空 profile 必须清掉全部三个覆盖，样式表默认值才能回来
    // —— 否则残留的 -rgb/-ink 让按钮和选中环继续用上一个 profile 的色。
    root.style.removeProperty("--rxy-accent")
    root.style.removeProperty("--rxy-accent-rgb")
    root.style.removeProperty("--rxy-accent-ink")
  }
  if (background) root.style.setProperty("--rxy-bg", background)
  if (foreground) root.style.setProperty("--rxy-fg", foreground)
  root.dataset.themeId = theme_id ?? (resolved.mode === "dark" ? "rxy-dark" : "rxy-light")
  try {
    document.cookie = `rxy_theme=${resolved.mode};path=/;samesite=lax;max-age=31536000`
  } catch {
    // best effort
  }
}
