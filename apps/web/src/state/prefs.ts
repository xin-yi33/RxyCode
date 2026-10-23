import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect } from "react"

import { applyAppearance, resolveAppearance } from "../lib/appearance"
import { readLocaleCookie, type LocaleSetting } from "../lib/i18n"
import { createClient, type Preferences } from "../sdk/client"
import { useAuth } from "../features/auth/useAuth"

const api = createClient()

export function usePreferences() {
  const auth = useAuth()
  return useQuery({
    queryKey: ["preferences"],
    queryFn: ({ signal }) => api.getPreferences(signal),
    enabled: auth.status === "authed",
    staleTime: 60_000,
  })
}

export function usePatchPreferences() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Parameters<typeof api.patchPreferences>[0]) =>
      api.patchPreferences(body),
    onSuccess: (data) => {
      queryClient.setQueryData(["preferences"], data)
      applyAppearance(resolveAppearance(data))
    },
  })
}

// Default preference shape used when the server payload is unavailable
// (guests, offline) — matches the backend defaults.
export function defaultPreferences(): Preferences {
  return {
    revision: 0,
    locale: "auto",
    sidebar: { grouping: "merged", sort: "updated_at", show_projects: true },
    appearance: {
      mode: "system",
      separate_modes: false,
      shared: {},
      light: null,
      dark: null,
      reduced_motion: "system",
      diff_markers: "color",
    },
  }
}

// Guest fallback: cookie-backed mode until preferences land.
export function guestMode(): "light" | "dark" {
  try {
    const match = document.cookie.match(/(?:^|;\s*)rxy_theme=(light|dark)\b/)
    if (match) return match[1] as "light" | "dark"
  } catch {
    // ignore
  }
  const systemDark =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-color-scheme: dark)").matches
  return systemDark ? "dark" : "light"
}

export function localeSettingFromPrefs(
  prefs: Preferences | null | undefined,
): LocaleSetting {
  const locale = prefs?.locale
  if (locale === "zh-CN" || locale === "en" || locale === "auto") return locale
  return readLocaleCookie()
}

// Applies resolved appearance to <html> whenever prefs change. For guests the
// cookie mode is applied so there's no flash of the wrong theme; for signed-in
// users the server is the only source of truth — until it answers we keep the
// stylesheet default instead of guessing from the OS preference.
export function useApplyAppearance(prefs: Preferences | null | undefined) {
  const auth = useAuth()
  useEffect(() => {
    if (prefs) {
      applyAppearance(resolveAppearance(prefs))
      return
    }
    if (auth.status !== "guest") return
    const base = defaultPreferences()
    base.appearance.mode = guestMode()
    applyAppearance(resolveAppearance(base))
  }, [prefs, auth.status])
}
