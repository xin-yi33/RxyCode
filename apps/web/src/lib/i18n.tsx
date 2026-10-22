import { createContext, useContext, useMemo, type ReactNode } from "react"

// Locale resolution: server preference wins when signed in; the `rxy_locale`
// cookie carries the visitor/auto choice so first paint is never in the wrong
// language. No localStorage — the bundle's security contract forbids it.
export type Locale = "zh-CN" | "en"
export type LocaleSetting = "auto" | Locale

const DICT = {
  "app.search": { "zh-CN": "搜索", en: "Search" },
  "app.newTask": { "zh-CN": "新任务", en: "New task" },
  "app.scheduled": { "zh-CN": "定时任务", en: "Scheduled" },
  "app.sessions": { "zh-CN": "会话", en: "Chats" },
  "app.pinned": { "zh-CN": "置顶", en: "Pinned" },
  "app.recent": { "zh-CN": "最近", en: "Recent" },
  "app.projects": { "zh-CN": "项目", en: "Projects" },
  "app.settings": { "zh-CN": "设置", en: "Settings" },
  "app.logout": { "zh-CN": "登出", en: "Log out" },
  "app.login": { "zh-CN": "登录", en: "Log in" },
  "app.register": { "zh-CN": "注册", en: "Sign up" },
  "app.noSessions": { "zh-CN": "还没有会话", en: "No chats yet" },
  "app.loading": { "zh-CN": "加载中…", en: "Loading…" },
  "app.retry": { "zh-CN": "重试", en: "Retry" },
  "app.cancel": { "zh-CN": "取消", en: "Cancel" },
  "app.save": { "zh-CN": "保存", en: "Save" },
  "app.delete": { "zh-CN": "删除", en: "Delete" },
  "app.confirm": { "zh-CN": "确认", en: "Confirm" },
  "app.close": { "zh-CN": "关闭", en: "Close" },
  "app.all": { "zh-CN": "全部", en: "All" },
  "session.rename": { "zh-CN": "重命名", en: "Rename" },
  "session.pin": { "zh-CN": "置顶", en: "Pin" },
  "session.unpin": { "zh-CN": "取消置顶", en: "Unpin" },
  "session.archive": { "zh-CN": "归档", en: "Archive" },
  "session.unarchive": { "zh-CN": "取消归档", en: "Unarchive" },
  "session.delete": { "zh-CN": "删除会话", en: "Delete chat" },
  "session.moveTo": { "zh-CN": "移动到项目", en: "Move to project" },
  "session.archivedBanner": {
    "zh-CN": "此会话已归档，内容只读。取消归档后可继续对话。",
    en: "This chat is archived and read-only. Unarchive it to continue.",
  },
  "session.deleteConfirm": {
    "zh-CN": "删除后无法恢复，会话与运行历史将被清除。",
    en: "This permanently deletes the chat and its run history.",
  },
  "search.placeholder": { "zh-CN": "搜索会话、项目、文件…", en: "Search chats, projects, files…" },
  "search.empty": { "zh-CN": "输入以搜索", en: "Type to search" },
  "search.noResults": { "zh-CN": "没有匹配结果", en: "No results" },
  "search.loadMore": { "zh-CN": "加载更多", en: "Load more" },
  "search.closeTip": { "zh-CN": "关闭搜索", en: "Close search" },
  "schedule.title": { "zh-CN": "定时任务", en: "Scheduled tasks" },
  "schedule.new": { "zh-CN": "新建定时任务", en: "New scheduled task" },
  "schedule.enabled": { "zh-CN": "已启用", en: "Enabled" },
  "schedule.paused": { "zh-CN": "已暂停", en: "Paused" },
  "schedule.runNow": { "zh-CN": "立即运行", en: "Run now" },
  "schedule.next": { "zh-CN": "下次执行", en: "Next run" },
  "settings.general": { "zh-CN": "通用", en: "General" },
  "settings.appearance": { "zh-CN": "外观", en: "Appearance" },
  "settings.notifications": { "zh-CN": "通知", en: "Notifications" },
  "settings.security": { "zh-CN": "安全", en: "Security" },
  "settings.archived": { "zh-CN": "已归档会话", en: "Archived chats" },
  "settings.addmodel": { "zh-CN": "模型", en: "Models" },
} as const

export type I18nKey = keyof typeof DICT

const LOCALE_COOKIE = "rxy_locale"

export function readLocaleCookie(): LocaleSetting {
  try {
    const match = document.cookie.match(/(?:^|;\s*)rxy_locale=(auto|zh-CN|en)\b/)
    return (match?.[1] as LocaleSetting) ?? "auto"
  } catch {
    return "auto"
  }
}

export function persistLocaleCookie(value: LocaleSetting): void {
  try {
    document.cookie = `${LOCALE_COOKIE}=${value};path=/;samesite=lax;max-age=31536000`
  } catch {
    // best effort — the in-memory value still applies this session
  }
}

export function resolveLocale(setting: LocaleSetting): Locale {
  if (setting === "zh-CN" || setting === "en") return setting
  const nav = typeof navigator === "undefined" ? "en" : navigator.language
  return nav.toLowerCase().startsWith("zh") ? "zh-CN" : "en"
}

const I18nContext = createContext<{ locale: Locale; t: (key: I18nKey) => string }>({
  locale: "zh-CN",
  t: (key) => DICT[key]?.["zh-CN"] ?? key,
})

export function I18nProvider({
  setting,
  children,
}: {
  setting: LocaleSetting
  children: ReactNode
}) {
  const value = useMemo(() => {
    const locale = resolveLocale(setting)
    return {
      locale,
      t: (key: I18nKey) => DICT[key]?.[locale] ?? DICT[key]?.["zh-CN"] ?? key,
    }
  }, [setting])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() {
  return useContext(I18nContext)
}
