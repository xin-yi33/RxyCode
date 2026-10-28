import { useEffect, useRef, useState } from "react"
import { Link, NavLink, Navigate, useLocation, useParams } from "react-router"

import { IconChevronDown, IconClose, IconMenu } from "../../components/icons"
import { useI18n } from "../../lib/i18n"
import { lastAppPath } from "../../lib/lastAppPath"
import { loginPathFor } from "../../app/AuthGate"
import { useAuth } from "../auth/useAuth"
import {
  AppearanceSection,
  ArchivedSection,
  GeneralSection,
  NotificationsSection,
} from "./SettingsSections"
import { SecuritySection } from "./SecuritySection"
import { ModelsSection } from "./ModelsSection"
import FeedbackSection from "../feedback/FeedbackSection"

// 私有分区：访客看到登录入口而非空数据/401（§01 路由表）。
function PrivateSetting({ children }: { children: React.ReactNode }) {
  const auth = useAuth()
  const { t } = useI18n()
  const location = useLocation()
  if (auth.status !== "authed") {
    return (
      <div className="rounded-xl border border-border bg-card p-6">
        <p className="text-sm text-muted">{t("settings.loginRequired")}</p>
        <Link
          className="mt-3 inline-block text-sm font-medium underline"
          to={loginPathFor(location.pathname, location.search)}
        >
          {t("settings.login")}
        </Link>
      </div>
    )
  }
  return <>{children}</>
}

// 契约分区 ID（UI-2026-10-22 §01 路由表）；不要换成短名。
const SECTIONS = [
  { id: "general-settings", key: "settings.general", blurb: "settings.general.blurb" },
  { id: "appearance", key: "settings.appearance", blurb: "settings.appearance.blurb" },
  {
    id: "notifications",
    key: "settings.notifications",
    blurb: "settings.notifications.blurb",
  },
  { id: "security", key: "settings.security", blurb: "settings.security.blurb" },
  {
    id: "archived-chats",
    key: "settings.archived",
    blurb: "settings.archived.blurb",
  },
  { id: "addmodel", key: "settings.addmodel", blurb: "settings.addmodel.blurb" },
  { id: "feedback", key: "settings.feedback", blurb: "settings.feedback.blurb" },
] as const

type SectionId = (typeof SECTIONS)[number]["id"]

function sectionOf(raw: string | undefined): SectionId | null {
  const hit = SECTIONS.find((s) => s.id === raw)
  return hit ? hit.id : null
}

// /settings/:section 外壳：左侧分区导航 + 右侧面板。SET-01 返回应用、
// SET-02 六分区路由、SET-03 本地分区搜索；小屏分区导航走左侧抽屉
// （与会话侧栏同一套 slide-in 形态），不再是 <select>。
export function SettingsShell() {
  const params = useParams()
  const { t } = useI18n()
  const [filter, setFilter] = useState("")
  const [drawerOpen, setDrawerOpen] = useState(false)
  const drawerRef = useRef<HTMLDivElement>(null)
  const section = sectionOf(params.section)

  // 选中分区 → 路由变化 → 抽屉关闭。
  useEffect(() => setDrawerOpen(false), [section])

  // 抽屉打开期间：Esc 关闭、Tab/Shift+Tab 焦点圈禁在抽屉内、
  // 锁背景滚动、关闭后焦点回到触发按钮（与会话侧栏同一套行为）。
  useEffect(() => {
    if (!drawerOpen) return
    const root = drawerRef.current
    const previous = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    root
      ?.querySelector<HTMLElement>("button, a[href]")
      ?.focus({ preventScroll: true })

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault()
        setDrawerOpen(false)
        return
      }
      if (event.key !== "Tab" || !root) return
      const focusables = Array.from(
        root.querySelectorAll<HTMLElement>(
          "a[href], button:not([disabled]), input, select, textarea, " +
            '[tabindex]:not([tabindex="-1"])',
        ),
      )
      if (focusables.length === 0) return
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      if (!root.contains(document.activeElement)) {
        event.preventDefault()
        first.focus()
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener("keydown", onKey, true)
    return () => {
      document.removeEventListener("keydown", onKey, true)
      document.body.style.overflow = previousOverflow
      if (previous instanceof HTMLElement && previous.isConnected) {
        previous.focus({ preventScroll: true })
      }
    }
  }, [drawerOpen])

  if (!section) return <Navigate to="/settings/general-settings" replace />

  const current = SECTIONS.find((s) => s.id === section)
  const needle = filter.trim().toLowerCase()
  const visible = needle
    ? SECTIONS.filter(
        (s) =>
          t(s.key).toLowerCase().includes(needle) ||
          t(s.blurb).toLowerCase().includes(needle),
      )
    : SECTIONS
  const backTo = lastAppPath()

  const nav = (vertical: boolean) => (
    <nav
      className={vertical ? "space-y-1" : "w-64 shrink-0 space-y-1"}
      aria-label={t("settings.nav.aria")}
    >
      {visible.map((s) => (
        <NavLink
          key={s.id}
          to={`/settings/${s.id}`}
          aria-current={s.id === section ? "page" : undefined}
          className={({ isActive }) =>
            "block rounded-md px-3 py-2 text-sm " +
            (isActive ? "bg-card font-medium" : "text-muted hover:bg-card/60")
          }
        >
          {t(s.key)}
        </NavLink>
      ))}
      {visible.length === 0 ? (
        <p className="px-3 py-2 text-xs text-muted">{t("settings.nav.empty")}</p>
      ) : null}
    </nav>
  )

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 px-4 py-6 md:flex-row md:gap-6 md:py-8">
      <aside className="md:w-64 md:shrink-0">
        <div className="mb-3 space-y-2 md:space-y-3">
          <Link
            to={backTo}
            className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground"
          >
            ← {t("settings.backToApp")}
          </Link>
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t("settings.nav.search")}
            aria-label={t("settings.nav.search")}
            className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm"
          />
        </div>
        {/* 手机：分区走左侧滑入抽屉（会话侧栏同款），不横向挤六项。 */}
        <button
          type="button"
          data-testid="settings-nav-trigger"
          aria-haspopup="dialog"
          aria-expanded={drawerOpen}
          className={
            "rxy-ghost-control flex w-full items-center justify-between " +
            "rounded-md border border-border bg-background px-3 py-2 text-sm md:hidden"
          }
          onClick={() => setDrawerOpen(true)}
        >
          <span className="flex min-w-0 items-center gap-2">
            <IconMenu size={16} className="shrink-0 text-muted" />
            <span className="truncate">{current ? t(current.key) : t("settings.nav.aria")}</span>
          </span>
          <IconChevronDown size={14} className="shrink-0 text-muted" />
        </button>
        <div className="hidden md:block">{nav(false)}</div>
      </aside>
      <div className="min-w-0 max-w-3xl flex-1">
        {section === "general-settings" ? <GeneralSection /> : null}
        {section === "appearance" ? <AppearanceSection /> : null}
        {section === "notifications" ? (
          <PrivateSetting>
            <NotificationsSection />
          </PrivateSetting>
        ) : null}
        {section === "security" ? (
          <PrivateSetting>
            <SecuritySection />
          </PrivateSetting>
        ) : null}
        {section === "archived-chats" ? (
          <PrivateSetting>
            <ArchivedSection />
          </PrivateSetting>
        ) : null}
        {section === "addmodel" ? (
          <PrivateSetting>
            <ModelsSection />
          </PrivateSetting>
        ) : null}
        {section === "feedback" ? (
          <PrivateSetting>
            <FeedbackSection />
          </PrivateSetting>
        ) : null}
      </div>
      {drawerOpen ? (
        <>
          <button
            type="button"
            aria-label={t("settings.nav.close")}
            className="fixed inset-0 z-30 bg-black/40 md:hidden"
            onClick={() => setDrawerOpen(false)}
          />
          <div
            ref={drawerRef}
            data-testid="settings-nav-drawer"
            role="dialog"
            aria-modal="true"
            aria-label={t("settings.nav.aria")}
            className={
              "rxy-sidebar-drawer fixed inset-y-0 left-0 z-40 flex w-72 " +
              "flex-col border-r border-border bg-sidebar md:hidden"
            }
          >
            <div className="flex items-center justify-between px-3 py-3">
              <span className="px-1 text-sm font-semibold">
                {t("settings.nav.aria")}
              </span>
              <button
                type="button"
                aria-label={t("settings.nav.close")}
                className="rounded-md p-1 text-muted hover:bg-card"
                onClick={() => setDrawerOpen(false)}
              >
                <IconClose size={18} />
              </button>
            </div>
            {/* 点当前分区也要关抽屉 —— 命中同一路由时不会有路由变化。 */}
            <div
              className="flex-1 overflow-y-auto px-2 pb-3"
              onClick={(event) => {
                if ((event.target as HTMLElement).closest("a")) {
                  setDrawerOpen(false)
                }
              }}
            >
              {nav(true)}
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}
