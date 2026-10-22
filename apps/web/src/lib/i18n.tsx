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
  "session.share": { "zh-CN": "分享", en: "Share" },
  "session.linkCopied": { "zh-CN": "链接已复制", en: "Link copied" },
  "session.copyFail": {
    "zh-CN": "复制失败，请手动复制地址栏链接",
    en: "Copy failed — copy the address bar link manually",
  },
  "session.moveOut": { "zh-CN": "移出项目", en: "Move out of project" },
  "session.searchProjects": { "zh-CN": "搜索项目…", en: "Search projects…" },
  "session.memoryWarn": {
    "zh-CN": "移动后该会话将使用目标项目的记忆边界，不会带入其他项目的记忆。确认继续？",
    en: "After moving, this chat uses the target project's memory scope — memories from other projects are not carried over. Continue?",
  },
  "session.busyBlocked": {
    "zh-CN": "会话有正在运行的任务，请先停止后再操作",
    en: "This chat has an active run — stop it first",
  },
  "session.deleteForever": {
    "zh-CN": "永久删除，无法撤销",
    en: "Permanently deleted — this cannot be undone",
  },
  "session.deleteChatTitle": { "zh-CN": "删除聊天", en: "Delete chat" },
  "session.move": { "zh-CN": "移动", en: "Move" },
  "sidebar.organize": { "zh-CN": "整理侧边栏", en: "Organize sidebar" },
  "sidebar.sortBy": { "zh-CN": "聊天排序方式", en: "Chat sort order" },
  "sidebar.grouping": { "zh-CN": "分组", en: "Grouping" },
  "sidebar.groupProject": { "zh-CN": "按项目显示", en: "Group by project" },
  "sidebar.groupMerged": { "zh-CN": "合并显示", en: "Merged" },
  "sidebar.sortUpdated": { "zh-CN": "最近更新", en: "Recently updated" },
  "sidebar.sortManual": { "zh-CN": "手动排序", en: "Manual order" },
  "sidebar.showProjects": { "zh-CN": "显示项目区", en: "Show projects" },
  "sidebar.collapse": { "zh-CN": "折叠分区", en: "Collapse section" },
  "sidebar.expand": { "zh-CN": "展开分区", en: "Expand section" },
  "sidebar.moveUp": { "zh-CN": "上移", en: "Move up" },
  "sidebar.moveDown": { "zh-CN": "下移", en: "Move down" },
  "sidebar.newChatHere": { "zh-CN": "新聊天", en: "New chat" },
  "project.create": { "zh-CN": "创建项目", en: "Create project" },
  "project.createTitle": { "zh-CN": "创建项目", en: "Create project" },
  "project.namePlaceholder": { "zh-CN": "项目名称", en: "Project name" },
  "project.purpose": {
    "zh-CN": "项目把相关聊天与记忆组织在一起，聊天可以随时移动归属。",
    en: "Projects keep related chats and memory together; chats can be moved between projects.",
  },
  "project.memoryDefault": { "zh-CN": "默认记忆", en: "Default memory" },
  "project.memoryDefaultHint": {
    "zh-CN": "可使用跨会话的用户记忆",
    en: "May use your cross-session memory",
  },
  "project.memoryOnly": { "zh-CN": "仅限项目的记忆", en: "Project-only memory" },
  "project.memoryOnlyHint": {
    "zh-CN": "记忆只在项目内检索，不会出现在其他会话",
    en: "Memory is retrieved only inside this project",
  },
  "project.rename": { "zh-CN": "重命名项目", en: "Rename project" },
  "project.settings": { "zh-CN": "项目设置", en: "Project settings" },
  "project.delete": { "zh-CN": "删除项目", en: "Delete project" },
  "project.deleteConfirm": {
    "zh-CN": "聊天与文件会保留并移出项目；项目本身将被删除。",
    en: "Chats and files are kept and moved out; the project itself is deleted.",
  },
  "project.deleteTitle": { "zh-CN": "删除项目", en: "Delete project" },
  "project.chats": { "zh-CN": "聊天", en: "Chats" },
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
  "settings.security": { "zh-CN": "账户安全与登录", en: "Account security & sign-in" },
  "settings.archived": { "zh-CN": "已归档的聊天", en: "Archived chats" },
  "settings.addmodel": { "zh-CN": "模型添加", en: "Add model" },
  "settings.general.blurb": { "zh-CN": "应用界面语言", en: "App display language" },
  "settings.appearance.blurb": {
    "zh-CN": "主题、颜色与字号",
    en: "Theme, colors and font size",
  },
  "settings.notifications.blurb": {
    "zh-CN": "通知分类与渠道",
    en: "Notification categories and channels",
  },
  "settings.security.blurb": {
    "zh-CN": "密码、密钥与登录会话",
    en: "Password, passkeys and sessions",
  },
  "settings.archived.blurb": {
    "zh-CN": "查看、恢复或永久删除",
    en: "View, restore or permanently delete",
  },
  "settings.addmodel.blurb": {
    "zh-CN": "连接自有 API Key",
    en: "Connect your own API keys",
  },
  "settings.backToApp": { "zh-CN": "返回应用", en: "Back to app" },
  "settings.nav.search": { "zh-CN": "搜索设置", en: "Search settings" },
  "settings.nav.aria": { "zh-CN": "设置分区", en: "Settings sections" },
  "settings.nav.empty": { "zh-CN": "没有匹配的分区", en: "No matching section" },
  "settings.loginRequired": {
    "zh-CN": "登录后可管理此分区。",
    en: "Sign in to manage this section.",
  },
  "settings.login": { "zh-CN": "去登录", en: "Sign in" },
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
