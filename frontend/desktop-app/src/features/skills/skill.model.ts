export const CREATE_SKILL_PROMPT = `请根据我的需求搜索并安装一个 skill。

需求：{need}

步骤：1) 在 GitHub 搜索带 SKILL.md 的仓库 2) 只选用真实搜到的结果 3) 调用 find_and_download_skill 或 install_skill_from_url 安装 4) 汇报安装路径、简介和适用范围。不要编造未搜到的仓库。`

export interface SkillMarketItem {
  name: string
  repo?: string
  path?: string
  source: string
  stars: number
  description: string
  scope: string
  installed: boolean
}

export function mapSkillMarketItem(raw: Record<string, unknown>, installedNames: ReadonlySet<string>): SkillMarketItem {
  const name = String(raw.name ?? '')
  return {
    name,
    repo: typeof raw.repo === 'string' ? raw.repo : undefined,
    path: typeof raw.path === 'string' ? raw.path : undefined,
    source: String(raw.source ?? ''),
    stars: typeof raw.stars === 'number' ? raw.stars : Number(raw.stargazers_count ?? 0) || 0,
    description: String(raw.description ?? ''),
    scope: String(raw.scope ?? raw.repo ?? ''),
    installed: installedNames.has(name)
  }
}

export function parseSkillSearch(raw: unknown, installedNames: ReadonlySet<string>): SkillMarketItem[] {
  if (raw == null || typeof raw !== 'object') return []
  const list = (raw as { skills?: unknown }).skills
  if (!Array.isArray(list)) return []
  return list
    .filter((item): item is Record<string, unknown> => item != null && typeof item === 'object')
    .map((item) => mapSkillMarketItem(item, installedNames))
    .filter((row) => row.name !== '')
}

export function skillPortraitSrc(name: string): string {
  const key = name.toLowerCase()
  if (key.includes('git')) return 'teams/github.png'
  if (key.includes('debug') || key.includes('bug') || key.includes('test') || key.includes('tdd')) return 'teams/skill-debug.png'
  if (key.includes('doc') || key.includes('readme') || key.includes('write')) return 'teams/skill-docs.png'
  if (key.includes('hub') || key.includes('skill')) return 'teams/skill-hub.png'
  const icons = ['teams/skill-code.png', 'teams/skill-debug.png', 'teams/skill-docs.png', 'teams/skill-hub.png']
  let hash = 0
  for (const ch of key) hash = (hash + ch.charCodeAt(0)) % icons.length
  return icons[hash] ?? 'teams/skill-code.png'
}

export function pluginPortraitSrc(name: string): string {
  return name.toLowerCase().includes('git') ? 'teams/github.png' : 'teams/plugin.png'
}
