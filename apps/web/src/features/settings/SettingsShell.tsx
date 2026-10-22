import { NavLink, Navigate, useParams } from "react-router"

import { useI18n } from "../../lib/i18n"
import {
  AppearanceSection,
  ArchivedSection,
  GeneralSection,
  NotificationsSection,
} from "./SettingsSections"
import { SecuritySection } from "./SecuritySection"
import { ModelsSection } from "./ModelsSection"

const SECTIONS = [
  { id: "general", key: "settings.general" },
  { id: "appearance", key: "settings.appearance" },
  { id: "notifications", key: "settings.notifications" },
  { id: "security", key: "settings.security" },
  { id: "archived", key: "settings.archived" },
  { id: "models", key: "settings.addmodel" },
] as const

// /settings/:section 外壳：左侧分区导航 + 右侧面板。
export function SettingsShell() {
  const { section = "general" } = useParams()
  const { t } = useI18n()
  const known = SECTIONS.some((s) => s.id === section)
  if (!known) return <Navigate to="/settings/general" replace />

  return (
    <div className="mx-auto flex max-w-5xl gap-6 px-4 py-8">
      <nav className="w-40 shrink-0 space-y-1" aria-label="设置分区">
        {SECTIONS.map((s) => (
          <NavLink
            key={s.id}
            to={`/settings/${s.id}`}
            className={({ isActive }) =>
              "block rounded-md px-3 py-2 text-sm " +
              (isActive ? "bg-card font-medium" : "text-muted hover:bg-card/60")
            }
          >
            {t(s.key)}
          </NavLink>
        ))}
      </nav>
      <div className="min-w-0 flex-1">
        {section === "general" ? <GeneralSection /> : null}
        {section === "appearance" ? <AppearanceSection /> : null}
        {section === "notifications" ? <NotificationsSection /> : null}
        {section === "security" ? <SecuritySection /> : null}
        {section === "archived" ? <ArchivedSection /> : null}
        {section === "models" ? <ModelsSection /> : null}
      </div>
    </div>
  )
}
