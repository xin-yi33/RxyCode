import { create } from "zustand"

export type ThemeName = "light" | "dark"
export type PermissionProfile = "confirm" | "full"

export type ComposerDraft = {
  text: string
  // request_id lives with the draft: a network failure retries with the same
  // id; editing the text after a failure mints a new one (see Composer).
  requestId: string
  permission: PermissionProfile
}

type UiState = {
  theme: ThemeName
  offline: boolean
  sidebarOpen: boolean
  consoleOpen: boolean
  drafts: Record<string, ComposerDraft>
  setTheme: (theme: ThemeName) => void
  toggleTheme: () => void
  setOffline: (offline: boolean) => void
  setSidebarOpen: (open: boolean) => void
  toggleSidebar: () => void
  setConsoleOpen: (open: boolean) => void
  toggleConsole: () => void
  draftFor: (sessionId: string) => ComposerDraft
  setDraft: (sessionId: string, draft: ComposerDraft) => void
  clearDraft: (sessionId: string) => void
}

const EMPTY_DRAFT: ComposerDraft = {
  text: "",
  requestId: "",
  permission: "confirm",
}

// The theme persists in the `rxy_theme` cookie, not storage — the shipped
// bundle must not touch localStorage (tests/web/w3 security contract).
const THEME_COOKIE = "rxy_theme"

function readTheme(): ThemeName {
  if (typeof document === "undefined") return "light"
  const match = document.cookie.match(/(?:^|;\s*)rxy_theme=(dark|light)\b/)
  return match ? (match[1] as ThemeName) : "light"
}

function persistTheme(theme: ThemeName): void {
  document.cookie = `${THEME_COOKIE}=${theme};path=/;samesite=lax;max-age=31536000`
}

export const useUi = create<UiState>()((set, get) => ({
  theme: readTheme(),
  offline: false,
  sidebarOpen: true,
  consoleOpen: false,
  drafts: {},
  setTheme: (theme) => {
    persistTheme(theme)
    set({ theme })
  },
  toggleTheme: () => {
    const theme = get().theme === "dark" ? "light" : "dark"
    persistTheme(theme)
    set({ theme })
  },
  setOffline: (offline) => set({ offline }),
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  toggleSidebar: () => set({ sidebarOpen: !get().sidebarOpen }),
  setConsoleOpen: (consoleOpen) => set({ consoleOpen }),
  toggleConsole: () => set({ consoleOpen: !get().consoleOpen }),
  draftFor: (sessionId) => get().drafts[sessionId] ?? EMPTY_DRAFT,
  setDraft: (sessionId, draft) =>
    set({ drafts: { ...get().drafts, [sessionId]: draft } }),
  clearDraft: (sessionId) => {
    const drafts = { ...get().drafts }
    delete drafts[sessionId]
    set({ drafts })
  },
}))
