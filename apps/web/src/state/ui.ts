import { create } from "zustand"

export type ThemeName = "light" | "dark"
export type PermissionProfile = "confirm" | "full"

export type ComposerDraft = {
  text: string
  // request_id lives with the draft: a network failure retries with the same
  // id; editing the text after a failure mints a new one (see Composer).
  requestId: string
  permission: PermissionProfile
  // 选中的模型引用（"m_…" 或 "platform"）。undefined = 跟随服务端
  // default_model_ref；幂等范围含模型 —— 改选会重置 requestId。
  modelRef?: string | null
}

type UiState = {
  theme: ThemeName
  offline: boolean
  sidebarOpen: boolean
  consoleOpen: boolean
  searchOpen: boolean
  drafts: Record<string, ComposerDraft>
  // 访客登录跳转前置位：登录返回后 Composer 显示“草稿已保留”横幅，
  // 绝不自动重新发送（PRD §3.3 禁止自动提交）。
  pendingIntent: boolean
  // 409 DEVICE_IN_USE：任一请求撞上“另一台设备使用中”就置位，
  // ConsoleShell 顶层的 <DeviceConflictModal> 据此弹全局模态。
  deviceConflict: boolean
  // 一次性通知文案（“链接已复制”等）——ToastHost 自动消退。
  toast: { id: number; text: string } | null
  setTheme: (theme: ThemeName) => void
  toggleTheme: () => void
  setOffline: (offline: boolean) => void
  setSidebarOpen: (open: boolean) => void
  toggleSidebar: () => void
  setConsoleOpen: (open: boolean) => void
  toggleConsole: () => void
  setSearchOpen: (open: boolean) => void
  setPendingIntent: (value: boolean) => void
  setDeviceConflict: (value: boolean) => void
  showToast: (text: string) => void
  draftFor: (sessionId: string) => ComposerDraft
  setDraft: (sessionId: string, draft: ComposerDraft) => void
  patchDraft: (sessionId: string, patch: Partial<ComposerDraft>) => void
  clearDraft: (sessionId: string) => void
  // 登出/换账号：清空全部草稿与登录意图（PRD §3.3.5 —— 草稿按身份隔离）。
  resetDrafts: () => void
}

const EMPTY_DRAFT: ComposerDraft = {
  text: "",
  requestId: "",
  permission: "confirm",
  modelRef: undefined,
}

// The theme persists in the `rxy_theme` cookie, not storage — the shipped
// bundle must not touch localStorage (tests/web/w3 security contract).
const THEME_COOKIE = "rxy_theme"

function readTheme(): ThemeName {
  if (typeof document === "undefined") return "light"
  try {
    const match = document.cookie.match(/(?:^|;\s*)rxy_theme=(dark|light)\b/)
    return match ? (match[1] as ThemeName) : "light"
  } catch {
    return "light"
  }
}

function persistTheme(theme: ThemeName): void {
  if (typeof document === "undefined") return
  try {
    document.cookie = `${THEME_COOKIE}=${theme};path=/;samesite=lax;max-age=31536000`
  } catch {
    // Cookie persistence is best-effort; keep the in-memory theme responsive
    // when the browser denies cookie access. Do not fall back to localStorage.
  }
}

export const useUi = create<UiState>()((set, get) => ({
  theme: readTheme(),
  offline: false,
  sidebarOpen: true,
  consoleOpen: false,
  searchOpen: false,
  drafts: {},
  pendingIntent: false,
  deviceConflict: false,
  toast: null,
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
  setSearchOpen: (searchOpen) => set({ searchOpen }),
  setPendingIntent: (pendingIntent) => set({ pendingIntent }),
  setDeviceConflict: (deviceConflict) => set({ deviceConflict }),
  showToast: (text) => set({ toast: { id: Date.now(), text } }),
  draftFor: (sessionId) => get().drafts[sessionId] ?? EMPTY_DRAFT,
  setDraft: (sessionId, draft) =>
    set({ drafts: { ...get().drafts, [sessionId]: draft } }),
  patchDraft: (sessionId, patch) =>
    set({
      drafts: {
        ...get().drafts,
        [sessionId]: { ...EMPTY_DRAFT, ...get().drafts[sessionId], ...patch },
      },
    }),
  clearDraft: (sessionId) => {
    const drafts = { ...get().drafts }
    delete drafts[sessionId]
    set({ drafts })
  },
  resetDrafts: () => set({ drafts: {}, pendingIntent: false }),
}))
