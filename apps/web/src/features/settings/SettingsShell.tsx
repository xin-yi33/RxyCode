import { useState } from "react"
import { Link, NavLink, Navigate, useLocation, useNavigate, useParams } from "react-router"

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
] as const

type SectionId = (typeof SECTIONS)[number]["id"]

function sectionOf(raw: string | undefined): SectionId | null {
  const hit = SECTIONS.find((s) => s.id === raw)
  return hit ? hit.id : null
}

// /settings/:section 外壳：左侧分区导航 + 右侧面板。SET-01 返回应用、
// SET-02 六分区路由、SET-03 本地分区搜索；小屏分区导航改下拉选择。
export function SettingsShell() {
  const params = useParams()
  const navigate = useNavigate()
  const { t } = useI18n()
  const [filter, setFilter] = useState("")
  const section = sectionOf(params.section)
  if (!section) return <Navigate to="/settings/general-settings" replace />

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
        {/* 手机：分区改下拉选择，不横向挤六项（规格 §01 自适应）。 */}
        <label className="block md:hidden">
          <span className="sr-only">{t("settings.nav.aria")}</span>
          <select
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={section}
            onChange={(e) => navigate(`/settings/${e.target.value}`)}
          >
            {SECTIONS.map((s) => (
              <option key={s.id} value={s.id}>
                {t(s.key)}
              </option>
            ))}
          </select>
        </label>
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
      </div>
    </div>
  )
}
