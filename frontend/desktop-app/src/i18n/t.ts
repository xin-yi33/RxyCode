export type LocaleId = 'zh-CN' | 'en'

const ZH: Record<string, string> = {
  settings: '设置',
  skills: '技能',
  newTask: '新任务',
  recycle: '回收站',
  general: '常规',
  appearance: '外观',
  models: '模型选择',
  addModel: '模型添加',
  mcp: 'MCP 服务管理',
  team: '团队与模型',
  pinned: '置顶',
  projects: '项目',
  recent: '最近',
  blocked: 'BLOCKED_PREREQUISITE'
}

const EN: Record<string, string> = {
  settings: 'Settings',
  skills: 'Skills',
  newTask: 'New task',
  recycle: 'Recycle bin',
  general: 'General',
  appearance: 'Appearance',
  models: 'Models',
  addModel: 'Add model',
  mcp: 'MCP',
  team: 'Team & models',
  pinned: 'Pinned',
  projects: 'Projects',
  recent: 'Recent',
  blocked: 'BLOCKED_PREREQUISITE'
}

const TABLES: Record<LocaleId, Record<string, string>> = {
  'zh-CN': ZH,
  en: EN
}

export function normalizeLocale(raw: string | null | undefined): LocaleId {
  const value = (raw ?? '').toLowerCase()
  if (value.startsWith('zh')) return 'zh-CN'
  if (value.startsWith('en')) return 'en'
  return 'zh-CN'
}

export function t(locale: LocaleId, key: string, vars: Record<string, string> = {}): string {
  const table = TABLES[locale] ?? TABLES['zh-CN']
  let text = table[key] ?? TABLES['zh-CN'][key] ?? key
  for (const [name, value] of Object.entries(vars)) {
    text = text.replaceAll(`{${name}}`, value)
  }
  return text
}

export function isChatTextLocalized(_locale: LocaleId, modelReply: string): string {
  return modelReply
}
