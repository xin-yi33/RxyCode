import { relative, resolve } from 'node:path'

export interface UsageSample {
  input_tokens: number | null
  output_tokens: number | null
  cache_hit_tokens: number | null
  cache_miss_tokens: number | null
  reporting_status: 'reported' | 'partial' | 'not_reported'
}

export function isMeaningfulProtocolEvent(message: Record<string, any>): boolean {
  const method = String(message.method ?? '')
  if (!method.startsWith('event/') || method === 'event/heartbeat' || method === 'event/server_heartbeat') return false
  if (method !== 'event/progress') return true
  const text = String(message.params?.text ?? '').toLowerCase()
  return !(
    text.includes('waiting for model response') ||
    text.includes('build in progress') ||
    text.includes('\u6b63\u5728\u7b49\u5f85\u6a21\u578b\u54cd\u5e94')
  )
}

export function hasInFlightTool(
  messages: Array<Record<string, any>>,
  sessionId: string,
  atMs: number,
  untilMs?: number
): boolean {
  const open = new Set<string>()
  for (const message of messages) {
    const method = String(message.method ?? '')
    const sid = String(message.params?.session_id ?? '')
    const at = Number(message.__at_ms)
    if (sid !== sessionId || !Number.isFinite(at)) continue
    if (untilMs !== undefined && at >= untilMs) continue
    const callId = String(message.params?.call_id ?? '')
    if (!callId) continue
    if (method === 'event/tool_begin' && at <= atMs) open.add(callId)
    if (method === 'event/tool_end' && at <= atMs) open.delete(callId)
  }
  return open.size > 0
}

export function hasInFlightRecovery(
  messages: Array<Record<string, any>>,
  sessionId: string,
  atMs: number,
  untilMs?: number
): boolean {
  let active = false
  for (const message of messages) {
    const method = String(message.method ?? '')
    const sid = String(message.params?.session_id ?? '')
    const at = Number(message.__at_ms)
    if (sid !== sessionId || !Number.isFinite(at)) continue
    if (untilMs !== undefined && at >= untilMs) continue
    if (at > atMs) continue
    if (method === 'event/recovery_started' || method === 'event/recovery_attempt') active = true
    if (method === 'event/recovery_resolved' || method === 'event/recovery_exhausted') active = false
  }
  return active
}

export interface UsageSummary {
  input_tokens: number | null
  output_tokens: number | null
  cache_hit_tokens: number | null
  cache_miss_tokens: number | null
  total_tokens: number | null
  reporting_status: UsageSample['reporting_status']
}

function sumKnown(values: Array<number | null>): number | null {
  const known = values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  return known.length === 0 ? null : known.reduce((sum, value) => sum + value, 0)
}

export function aggregateUsage(samples: UsageSample[]): UsageSummary {
  const input_tokens = sumKnown(samples.map((sample) => sample.input_tokens))
  const output_tokens = sumKnown(samples.map((sample) => sample.output_tokens))
  const cache_hit_tokens = sumKnown(samples.map((sample) => sample.cache_hit_tokens))
  const cache_miss_tokens = sumKnown(samples.map((sample) => sample.cache_miss_tokens))
  return {
    input_tokens,
    output_tokens,
    cache_hit_tokens,
    cache_miss_tokens,
    total_tokens: input_tokens === null && output_tokens === null ? null : (input_tokens ?? 0) + (output_tokens ?? 0),
    reporting_status: samples.some((sample) => sample.reporting_status === 'not_reported')
      ? samples.some((sample) => sample.reporting_status !== 'not_reported') ? 'partial' : 'not_reported'
      : samples.some((sample) => sample.reporting_status === 'partial') ? 'partial' : 'reported'
  }
}

export function cacheHitRate(summary: UsageSummary): number | null {
  if (summary.input_tokens === null || summary.cache_hit_tokens === null || summary.input_tokens <= 0) return null
  return summary.cache_hit_tokens / summary.input_tokens
}

export function terminalOutcomeIssue(status: string, finalAnswer: string, artifactOk = false): string | null {
  if (status === 'succeeded' && finalAnswer.trim().length === 0) {
    return 'succeeded task has no non-empty Final Answer'
  }
  if (status === 'queued' && finalAnswer.trim().length === 0) {
    return 'GUI session ended as queued without a Final Answer'
  }
  if (status === 'failed' || status === 'cancelled' || status === 'timed_out') {
    // A recovered write/edit that still left a Failed badge must not override a
    // passing smoke/play probe (T06 retry3 had CSV + probe ok).
    if (
      artifactOk &&
      /Tool (?:write|edit) did not complete|Artifact failed format validation|FirstTokenTimeoutError|no first response event before the deadline|idle deadline/i.test(finalAnswer)
    ) {
      return null
    }
    const detail = finalAnswer.trim().replace(/\s+/g, ' ').slice(0, 280)
    return detail.length > 0 ? `GUI session ${status}: ${detail}` : `GUI session ended as ${status}`
  }
  return null
}

export const requiredWebDeliverables = ['index.html', 'README.md', 'TEST-REPORT.md'] as const

export function missingWebDeliverables(files: string[]): string[] {
  const names = new Set(files.map((file) => file.replace(/\\/g, '/').split('/').pop() ?? file))
  return requiredWebDeliverables.filter((file) => !names.has(file))
}

const COMPANY_ADMIN_MODULE_PATTERNS = [
  /用户管理|用户列表|#users\b|data-view=["']users["']/i,
  /订单管理|订单列表|#orders\b|data-view=["']orders["']/i,
  /内容管理|内容页面|#content\b|data-view=["']content["']/i,
  /设置|#settings\b|data-view=["']settings["']|\bsettings\b/i,
  /分析|数据看板|统计|#analytics\b|dashboard/i
]

export function countCompanyAdminModules(text: string): number {
  const hay = String(text ?? '')
  return COMPANY_ADMIN_MODULE_PATTERNS.filter((pattern) => pattern.test(hay)).length
}

export function companyLoginProbeIssue(probe: Record<string, any>): string | null {
  const text = String(probe.adminText ?? probe.text ?? '')
  const modules = Number.isFinite(Number(probe.adminModules))
    ? Number(probe.adminModules)
    : countCompanyAdminModules(text)
  const reachedAdmin = probe.demoClicked === true || probe.navigated === true
  if (!reachedAdmin) {
    return 'company page has no working demo login (#btn-demo-login)'
  }
  if (modules < 4) {
    return `demo login did not open an admin console with users/orders/content/settings/analytics (found ${modules}/5)`
  }
  return null
}

export function companyWebsiteArtifactIssue(
  files: string[],
  readText?: (relativePath: string) => string
): string | null {
  const rels = files.map((file) => file.replace(/\\/g, '/'))
  const names = new Set(rels.map((file) => file.split('/').pop() ?? file))
  if (rels.some((file) => file.endsWith('.java') || file === 'pom.xml' || file.endsWith('/pom.xml'))) {
    return 'company website substituted Java/Spring/Maven; static HTML/CSS/JS is required'
  }
  const required = ['index.html', 'PLAN.md', 'README.md', 'TEST-REPORT.md']
  const missing = required.filter((file) => !names.has(file))
  if (missing.length > 0) return `company website is incomplete; missing ${missing.join(', ')}`
  if (!rels.some((file) => /(^|\/)admin\.html$/i.test(file))) {
    return 'company website is incomplete; missing admin.html'
  }
  if (readText === undefined) return null
  const combined = rels
    .filter((file) => /\.(html|js)$/i.test(file) && !file.includes('.rxy-play-probe'))
    .slice(0, 40)
    .map((file) => {
      try {
        return readText(file)
      } catch {
        return ''
      }
    })
    .join('\n')
  if (!/#btn-demo-login|id=["']btn-demo-login["']|data-demo-login/.test(combined)) {
    return 'company website has no demo login control (#btn-demo-login)'
  }
  if (!/localStorage/.test(combined)) {
    return 'company website has no localStorage persistence'
  }
  const publicHits = [
    /产品|服务|products?|services?/i,
    /团队|team/i,
    /案例|cases?/i,
    /联系|contact/i
  ].filter((pattern) => pattern.test(combined)).length
  if (publicHits < 3) {
    return 'company website is missing public home/products/team/cases/contact sections'
  }
  if (countCompanyAdminModules(combined) < 4) {
    return 'company website admin console is missing users/orders/content/settings/analytics modules'
  }
  return null
}

export function travelWebsiteArtifactIssue(
  files: string[],
  readText?: (relativePath: string) => string
): string | null {
  const rels = files.map((file) => file.replace(/\\/g, '/'))
  const names = new Set(rels.map((file) => file.split('/').pop() ?? file))
  const required = ['index.html', 'PLAN.md', 'README.md', 'TEST-REPORT.md', 'sources.md']
  const missing = required.filter((file) => !names.has(file))
  if (missing.length > 0) return `travel website is incomplete; missing ${missing.join(', ')}`
  if (!rels.some((file) => file.toLowerCase().endsWith('.csv'))) {
    return 'travel website is incomplete; missing budget CSV'
  }
  if (readText === undefined) return null
  const html = rels
    .filter((file) => /\.html$/i.test(file) && !file.includes('.rxy-play-probe'))
    .slice(0, 20)
    .map((file) => {
      try {
        return readText(file)
      } catch {
        return ''
      }
    })
    .join('\n')
  if (!/苏州/.test(html) || !/杭州/.test(html) || !/广州/.test(html)) {
    return 'travel website is missing Guangzhou/Suzhou/Hangzhou itinerary coverage'
  }
  if (!/3000/.test(html)) {
    return 'travel website is missing the CNY 3000 budget cap'
  }
  if (!/Day\s*1|第\s*1\s*天|D1\b/i.test(html)) {
    return 'travel website is missing a daily timetable'
  }
  if (!/雨|rain/i.test(html)) {
    return 'travel website is missing a rain plan'
  }
  if (!/备选|替代|alternatives?/i.test(html)) {
    return 'travel website is missing alternatives'
  }
  if (!/妆|造型|makeup|styling/i.test(html)) {
    return 'travel website is missing the makeup/styling session'
  }
  if (!/<select\b|<input\b|<button\b/i.test(html)) {
    return 'travel website has no interactive city/date/cost controls'
  }
  return null
}

export function marketBiArtifactIssue(
  files: string[],
  readText?: (relativePath: string) => string
): string | null {
  const rels = files.map((file) => file.replace(/\\/g, '/'))
  const names = new Set(rels.map((file) => file.split('/').pop() ?? file))
  const required = ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md']
  const missing = required.filter((file) => !names.has(file))
  if (missing.length > 0) return `market BI website is incomplete; missing ${missing.join(', ')}`
  if (!rels.some((file) => file.toLowerCase().endsWith('.csv'))) {
    return 'market BI website is incomplete; missing data CSV'
  }
  if (readText === undefined) return null
  const html = rels
    .filter((file) => /\.html$/i.test(file) && !file.includes('.rxy-play-probe'))
    .slice(0, 20)
    .map((file) => {
      try {
        return readText(file)
      } catch {
        return ''
      }
    })
    .join('\n')
  const assets = [
    /黄金|gold/i,
    /白银|silver/i,
    /纳斯达克|nasdaq/i,
    /标普|S&P|SPX|标普500/i
  ].filter((pattern) => pattern.test(html)).length
  if (assets < 3) {
    return 'market BI website is missing gold/silver/Nasdaq/S&P coverage'
  }
  if (!/风险|disclaimer|risk/i.test(html)) {
    return 'market BI website is missing a risk disclaimer'
  }
  if (!/<select\b|<input\b|<button\b/i.test(html)) {
    return 'market BI website has no interactive date/asset/metric controls'
  }
  if (usesRemoteCdn(html)) {
    return 'market BI website depends on a remote CDN instead of native HTML/CSS/JS'
  }
  return null
}

function usesRemoteCdn(html: string): boolean {
  return /cdn\.jsdelivr|unpkg\.com|cdnjs\.cloudflare|chart\.umd\.min\.js/i.test(html)
}

function joinedHtml(files: string[], readText: (relativePath: string) => string): string {
  return joinedWebText(files, readText, /\.html?$/i)
}

function joinedWebText(
  files: string[],
  readText: (relativePath: string) => string,
  pattern: RegExp = /\.(html?|js)$/i
): string {
  return files
    .map((file) => file.replace(/\\/g, '/'))
    .filter((file) => pattern.test(file) && !file.includes('.rxy-play-probe') && !/(^|\/)src\//i.test(file))
    .slice(0, 20)
    .map((file) => {
      try {
        return readText(file)
      } catch {
        return ''
      }
    })
    .join('\n')
}

export function evTcoArtifactIssue(
  files: string[],
  readText?: (relativePath: string) => string
): string | null {
  const rels = files.map((file) => file.replace(/\\/g, '/'))
  const names = new Set(rels.map((file) => file.split('/').pop() ?? file))
  const required = ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md']
  const missing = required.filter((file) => !names.has(file))
  if (missing.length > 0) return `EV TCO website is incomplete; missing ${missing.join(', ')}`
  if (!rels.some((file) => file.toLowerCase().endsWith('.csv'))) {
    return 'EV TCO website is incomplete; missing data CSV'
  }
  if (readText === undefined) return null
  const html = joinedHtml(rels, readText)
  if (!/广州/.test(html)) {
    return 'EV TCO website is missing Guangzhou family coverage'
  }
  if (!/TCO|总拥有|五年|5\s*年/i.test(html)) {
    return 'EV TCO website is missing five-year TCO coverage'
  }
  if (!/150,?000|250,?000|15\s*万|25\s*万/.test(html)) {
    return 'EV TCO website is missing the CNY 150k-250k purchase budget'
  }
  if (!/里程|mileage/i.test(html)) {
    return 'EV TCO website is missing annual mileage controls'
  }
  if (!/权重|weight/i.test(html)) {
    return 'EV TCO website is missing price/range/safety/space weights'
  }
  if (!/风险|不确定|uncertainty|disclaimer/i.test(html)) {
    return 'EV TCO website is missing risk or uncertainty disclosure'
  }
  if (!/<select\b|<input\b|<button\b/i.test(html)) {
    return 'EV TCO website has no interactive budget/mileage/weight controls'
  }
  if (usesRemoteCdn(html)) {
    return 'EV TCO website depends on a remote CDN instead of native HTML/CSS/JS'
  }
  return null
}

export function rentalDecisionArtifactIssue(
  files: string[],
  readText?: (relativePath: string) => string
): string | null {
  const rels = files.map((file) => file.replace(/\\/g, '/'))
  const names = new Set(rels.map((file) => file.split('/').pop() ?? file))
  const required = ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md']
  const missing = required.filter((file) => !names.has(file))
  if (missing.length > 0) return `rental decision website is incomplete; missing ${missing.join(', ')}`
  if (!rels.some((file) => file.toLowerCase().endsWith('.csv'))) {
    return 'rental decision website is incomplete; missing data CSV'
  }
  if (readText === undefined) return null
  if (rels.some((file) => /\.java$/i.test(file) || /(^|\/)pom\.xml$/i.test(file))) {
    return 'rental decision website substituted Java/Spring instead of a static HTML decision tool'
  }
  const html = joinedWebText(rels, readText)
  if (!/珠江新城|Zhujiang/i.test(html)) {
    return 'rental decision website is missing Zhujiang New Town commute coverage'
  }
  if (!/3500/.test(html)) {
    return 'rental decision website is missing the CNY 3500 rent cap'
  }
  if (!/60/.test(html)) {
    return 'rental decision website is missing the 60-minute commute cap'
  }
  if (!/搬家|日历|calendar|入住/i.test(html)) {
    return 'rental decision website is missing a moving calendar or move-in checklist'
  }
  if (!/地图|map|schematic/i.test(html)) {
    return 'rental decision website is missing a schematic map'
  }
  if (!/合同|解约|退租|termination/i.test(html) || !/风险|噪音|noise|维修/i.test(html)) {
    return 'rental decision website is missing contract/risk coverage'
  }
  if (!/权重|weight/i.test(html)) {
    return 'rental decision website is missing rent/commute/amenity weights'
  }
  if (!/<select\b|<input\b|<button\b/i.test(html)) {
    return 'rental decision website has no interactive filter/weight controls'
  }
  if (usesRemoteCdn(html)) {
    return 'rental decision website depends on a remote CDN instead of native HTML/CSS/JS'
  }
  return null
}

export const requiredSpringMysqlDeliverables = [
  'README.md',
  'DEVELOPMENT.md',
  'API.md',
  'ARCHITECTURE.md',
  'SECURITY.md',
  'MIGRATION-ROLLBACK.md',
  'TEST-REPORT.md'
] as const

/** JUnit *Test.java and *Tests.java both count. T09-55 was false-failed for CoffeeApplicationTests.java. */
export function isSpringMysqlTestJava(relativePath: string): boolean {
  return /(^|\/)src\/test\/java\/.+Tests?\.java$/i.test(relativePath.replace(/\\/g, '/'))
}

export function findProjectLocalMaven(files: string[]): string | null {
  const rels = files.map((file) => file.replace(/\\/g, '/'))
  const pickCmd = (candidates: string[]): string | null => {
    if (candidates.length === 0) return null
    return candidates.find((file) => /\.cmd$/i.test(file)) ?? candidates[0] ?? null
  }
  const dist = pickCmd(rels.filter((file) => /apache-maven-[^/]+\/bin\/mvn(\.cmd)?$/i.test(file)))
  if (dist !== null) return dist
  const wrapper = pickCmd(rels.filter((file) => /(^|\/)mvnw(\.cmd)?$/i.test(file)))
  if (wrapper !== null) return wrapper
  return pickCmd(rels.filter((file) => /(^|\/)mvn(\.cmd)?$/i.test(file) && !/\/lib\//i.test(file)))
}

export function springMysqlArtifactIssue(
  files: string[],
  readText?: (relativePath: string) => string
): string | null {
  const rels = files.map((file) => file.replace(/\\/g, '/'))
  const names = new Set(rels.map((file) => file.split('/').pop() ?? file))
  const hasPom = rels.some((file) => file === 'pom.xml' || file.endsWith('/pom.xml'))
  const javaFiles = rels.filter((file) => file.endsWith('.java'))
  const mainJava = javaFiles.filter((file) => !/(^|\/)src\/test\//i.test(file))
  const hasPy = rels.some((file) => file.endsWith('.py'))
  if (hasPy && javaFiles.length === 0 && !hasPom) {
    return 'spring-mysql artifact substituted Python/SQLite instead of Java 17 + Spring Boot + MySQL'
  }
  if (javaFiles.length === 0) return 'spring-mysql artifact has no .java source'
  if (!hasPom) return 'spring-mysql artifact has no pom.xml'
  if (!rels.some((file) => /Controller\.java$/i.test(file))) {
    return 'spring-mysql artifact has no *Controller.java REST layer'
  }
  if (mainJava.length < 5) {
    return 'spring-mysql artifact is a skeleton; need models, controllers, and services in addition to Application'
  }
  if (!rels.some((file) => /\/db\/migration\/.+\.sql$/i.test(file))) {
    return 'spring-mysql artifact has no Flyway SQL under db/migration'
  }
  if (!rels.some((file) => /\/resources\/static\/.+\.html$/i.test(file) || /(^|\/)index\.html$/i.test(file))) {
    return 'spring-mysql artifact has no static frontend HTML'
  }
  if (!rels.some((file) => /application\.(yml|yaml|properties)$/i.test(file))) {
    return 'spring-mysql artifact has no application.yml or application.properties'
  }
  if (!javaFiles.some((file) => isSpringMysqlTestJava(file))) {
    return 'spring-mysql artifact has no src/test/java *Test.java'
  }
  if (findProjectLocalMaven(rels) === null) {
    return 'spring-mysql artifact has no project-local Maven (mvnw or .tools/apache-maven)'
  }
  if (readText !== undefined) {
    const pomFile = rels.find((file) => file === 'pom.xml' || file.endsWith('/pom.xml'))
    if (pomFile !== undefined && !/spring-boot-starter-flyway/.test(readText(pomFile))) {
      return 'spring-mysql pom.xml must declare spring-boot-starter-flyway; Boot 4 does not auto-run flyway-core alone'
    }
  }
  if (readText !== undefined) {
    const javaText = javaFiles.map((file) => readText(file)).join('\n')
    if (!/@RestController/.test(javaText)) {
      return 'spring-mysql REST layer has no @RestController'
    }
    const testText = javaFiles
      .filter((file) => isSpringMysqlTestJava(file))
      .map((file) => readText(file))
      .join('\n')
    if (!/@SpringBootTest/.test(testText) || !/MockMvc/.test(testText) || !/\.perform\(/.test(testText)) {
      return 'spring-mysql tests do not start Spring or MockMvc; a class-load or empty contextLoads smoke is not enough'
    }
    const packageIssue = springBootTestPackageIssue(rels, readText)
    if (packageIssue !== null) return packageIssue
    if (/com\.fasterxml\.jackson\.databind/.test(javaText)) {
      return 'spring-mysql Boot 4 cannot import com.fasterxml.jackson.databind; use tools.jackson.databind or jsonPath'
    }
    if (/org\.springframework\.boot\.test\.autoconfigure\.web(?:mvc|\.servlet)/.test(javaText)) {
      return 'spring-mysql Boot 4 AutoConfigureMockMvc is org.springframework.boot.webmvc.test.autoconfigure, not org.springframework.boot.test.autoconfigure.web.servlet or org.springframework.boot.test.autoconfigure.webmvc'
    }
    const sqlText = rels.filter((file) => /\/db\/migration\/.+\.sql$/i.test(file)).map((file) => readText(file)).join('\n').toLowerCase()
    for (const table of ['users', 'products', 'inventory', 'orders', 'order_items']) {
      if (!new RegExp(`create table\\s+(if not exists\\s+)?${table}\\b`, 'i').test(sqlText)) {
        return `spring-mysql Flyway SQL does not CREATE TABLE ${table}`
      }
    }
    if (/create table\s+(if not exists\s+)?menus\b/i.test(sqlText) && !/create table\s+(if not exists\s+)?products\b/i.test(sqlText)) {
      return 'spring-mysql Flyway SQL created menus instead of products/inventory'
    }
    const configBlob = rels
      .filter((file) => /\.(yml|yaml|properties|xml|java)$/i.test(file))
      .map((file) => readText(file))
      .join('\n')
    if (/jdbc:h2:|<artifactId>\s*h2\s*<\/artifactId>|com\.h2database|org\.h2\.Driver|H2Dialect|jdbc:sqlite:/i.test(configBlob)) {
      return 'spring-mysql tests substituted H2/SQLite for MySQL 8'
    }
    const configFile = rels.find((file) => /application\.(yml|yaml|properties)$/i.test(file))
    if (configFile !== undefined) {
      const config = readText(configFile)
      if (!/\$\{(?:SPRING_DATASOURCE_|MYSQL_)/.test(config)) {
        return 'application config does not read datasource credentials from environment variables'
      }
      if (/ddl-auto:\s*validate/i.test(config)) {
        return 'spring-mysql jpa.hibernate.ddl-auto=validate fails before Flyway creates tables; use none or update'
      }
    }
    if (/write-dates-as-timestamps\s*:/i.test(configBlob)) {
      return 'spring-mysql Boot 4 Jackson 3 cannot bind spring.jackson.serialization.write-dates-as-timestamps; delete that key or use WRITE_DATES_AS_TIMESTAMPS'
    }
  }
  const missing = requiredSpringMysqlDeliverables.filter((file) => !names.has(file))
  if (missing.length > 0) return `spring-mysql artifact is incomplete; missing ${missing.join(', ')}`
  if (readText === undefined) return null
  const reportFile = rels.find((file) => /(^|\/)TEST-REPORT\.md$/i.test(file))
  if (reportFile !== undefined) {
    const report = readText(reportFile)
    if (/待填写|待执行|待验证|若干/.test(report)) {
      return 'spring-mysql TEST-REPORT.md uses placeholders instead of real Maven/API smoke counts'
    }
    const countIssue = mavenTestCountsIssue(report)
    if (countIssue !== null) return `spring-mysql TEST-REPORT.md ${countIssue}`
  }
  return null
}

function javaPackageFromPath(relativePath: string): string | null {
  const match = relativePath.replace(/\\/g, '/').match(/src\/(?:main|test)\/java\/(.+)\/[^/]+\.java$/i)
  return match === null ? null : match[1].replace(/\//g, '.')
}

export function springBootTestPackageIssue(
  files: string[],
  readText: (relativePath: string) => string
): string | null {
  const rels = files.map((file) => file.replace(/\\/g, '/'))
  const appPkgs = new Set<string>()
  for (const file of rels) {
    if (!file.endsWith('.java') || /(^|\/)src\/test\//i.test(file)) continue
    const text = readText(file)
    if (!/@SpringBootApplication/.test(text)) continue
    const pkg = javaPackageFromPath(file)
    if (pkg !== null) appPkgs.add(pkg)
  }
  if (appPkgs.size === 0) return null
  for (const file of rels) {
    if (!isSpringMysqlTestJava(file)) continue
    const text = readText(file)
    if (!/@SpringBootTest/.test(text)) continue
    if (/@SpringBootTest\s*\([^)]*classes\s*=/.test(text)) continue
    const pkg = javaPackageFromPath(file)
    if (pkg === null) continue
    const nestedOk = [...appPkgs].some((app) => pkg === app || pkg.startsWith(`${app}.`))
    if (!nestedOk) {
      return 'spring-mysql *Test.java package cannot find @SpringBootConfiguration; put tests in the application package or set @SpringBootTest(classes=...)'
    }
  }
  return null
}

export function scenariosFrom<T extends { id: string }>(scenarios: T[], fromId: string | null | undefined): T[] {
  if (fromId === null || fromId === undefined || fromId === '') return [...scenarios]
  const index = scenarios.findIndex((item) => item.id === fromId)
  if (index < 0) throw new Error(`--from=${fromId} is not a known scenario`)
  return scenarios.slice(index)
}

export function firstFailedOrNextId(
  results: Array<{ id: string; error: string | null; status: string }>
): string | null {
  const failed = results.find((item) => item.error !== null || item.status !== 'succeeded')
  if (failed !== undefined) return failed.id
  return results.at(-1)?.id ?? null
}

export interface LongSessionState {
  sessionId: string
  debugPort: number
  electronPid: number
  tempRoot: string
  workspaceDir: string
  profileDir: string
  dataDir: string
  passed: string[]
  failed: string | null
  next: string | null
}

export function mavenTestCountsIssue(text: string): string | null {
  const matches = [...text.matchAll(/Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+)/g)]
  if (matches.length === 0) {
    if (!/Tests run:\s*[1-9]|\b\d+\s*(?:passed|passing|通过)\b|通过\s*[1-9]/i.test(text)) {
      return 'has no real Maven test counts'
    }
    if (/<<< FAILURE!/i.test(text) || /(?:Failures|Errors):\s*[1-9]/i.test(text)) {
      return 'records Maven test failures or errors'
    }
    return null
  }
  const failed = matches.find((row) => Number(row[2]) > 0 || Number(row[3]) > 0)
  if (failed !== undefined) {
    return `records Failures: ${failed[2]}, Errors: ${failed[3]}`
  }
  if (Number(matches[matches.length - 1][1]) < 1) return 'records zero Maven tests'
  return null
}

export function missingOutputDirIssue(outputDir: string, primaryExists: boolean, underscoreExists: boolean): string | null {
  if (primaryExists) return null
  const underscored = outputDir.replaceAll('-', '_')
  if (underscoreExists && underscored !== outputDir) {
    return `wrote ${underscored} instead of ${outputDir}; hyphen directory is required`
  }
  return 'output directory was not created'
}

export function playProbeUrl(argv: string[]): string | undefined {
  return argv.find((arg) => arg.startsWith('http://') || arg.startsWith('https://'))
}

export function staticFilePath(root: string, requestUrl: string): string | null {
  const rel = decodeURIComponent(String(requestUrl.split('?')[0] ?? '')).replace(/^[/\\]+/, '') || 'index.html'
  if (rel.split(/[/\\]/).includes('..')) return null
  const resolved = resolve(root, rel)
  const back = relative(resolve(root), resolved)
  if (back.startsWith('..') || back.split(/[/\\]/).includes('..')) return null
  return resolved
}

export function webServeRoot(source: string, files: string[]): string {
  const rels = files.map((file) => file.replace(/\\/g, '/'))
  const indexes = rels.filter((file) => /(^|\/)index\.html$/i.test(file))
  if (indexes.length === 0) return source
  indexes.sort((a, b) => a.split('/').length - b.split('/').length || a.length - b.length)
  const chosen = indexes[0]!
  if (!chosen.includes('/')) return source
  return resolve(source, chosen.replace(/\/index\.html$/i, ''))
}

export function mysqlPartsFromJdbc(url: string): { MYSQL_HOST?: string; MYSQL_PORT?: string; MYSQL_DATABASE?: string } {
  const match = String(url).match(/^jdbc:mysql:\/\/([^:/?#]+)(?::(\d+))?(?:\/([^?;#]+))?/i)
  if (match === null) return {}
  const parts: { MYSQL_HOST?: string; MYSQL_PORT?: string; MYSQL_DATABASE?: string } = {
    MYSQL_HOST: match[1]
  }
  if (match[2] !== undefined && match[2].length > 0) parts.MYSQL_PORT = match[2]
  if (match[3] !== undefined && match[3].length > 0) parts.MYSQL_DATABASE = match[3]
  return parts
}

export function parseHudScore(text: string): number {
  const n = Number(String(text).replace(/[^0-9.-]/g, ''))
  return Number.isFinite(n) ? n : 0
}

export function firstTokenHardFail(firstTokenMs: number | null, firstEventMs: number | null): boolean {
  if (firstTokenMs === null || firstTokenMs <= 30_000) return false
  // Research-first tasks (T06-2) show tools immediately; first prose can arrive
  // after minutes of websearch/write. Hard-fail only when nothing visible landed in 30s.
  return firstEventMs === null || firstEventMs > 30_000
}

export function javaMainClassName(relativePath: string, source: string): string | null {
  if (!/public\s+static\s+void\s+main\s*\(/.test(source)) return null
  const pkg = source.match(/^\s*package\s+([A-Za-z0-9_.]+)\s*;/m)
  const simple = relativePath.replace(/\\/g, '/').split('/').pop()!.replace(/\.java$/, '')
  return pkg !== null ? `${pkg[1]}.${simple}` : simple
}

export function selectJavaSwingMain(files: Array<{ path: string; source: string }>): string | null {
  const scored = files.map((file) => {
    const rel = file.path.replace(/\\/g, '/')
    const className = javaMainClassName(rel, file.source)
    if (className === null) return null
    return {
      className,
      swing: /javax\.swing|\bJFrame\b/.test(file.source),
      testish: /(^|\/)(test|src\/test)\//i.test(rel) || /Test\.java$|Driver\.java$|Acceptance/i.test(rel)
    }
  }).filter((item): item is { className: string; swing: boolean; testish: boolean } => item !== null)
  const preferred = scored.find((item) => item.swing && !item.testish)
  if (preferred !== undefined) return preferred.className
  const swing = scored.find((item) => item.swing)
  return swing?.className ?? null
}

export function gameEnteredPlayableState(state: string, score: number): boolean {
  if (parseHudScore(String(score)) > 0) return true
  if (Number(score) > 0) return true
  return /running|playing|\brun\b|运行|进行|游玩/i.test(state)
}

export function gameMenuStillBlockingPlay(input: {
  overlayHidden?: boolean
  startVisible?: boolean
  state: string
  score: number
}): boolean {
  if (gameEnteredPlayableState(input.state, input.score)) return false
  // A hidden start overlay is not enough. T02 hid #btn-start after a
  // JS crash while #state stayed 待开始 and the canvas never painted.
  return true
}

export function parseDotEnv(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (line.length === 0 || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq <= 0) continue
    const key = line.slice(0, eq).trim()
    let value = line.slice(eq + 1).trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    out[key] = value
  }
  return out
}

export interface LayoutElement {
  id: string
  left: number
  top: number
  right: number
  bottom: number
}

export interface LayoutSnapshot {
  viewport: { width: number; height: number }
  horizontalScroll: number
  elements: LayoutElement[]
}

export interface LayoutIssue {
  kind: 'overlap' | 'clipped' | 'horizontal_scroll' | 'composer_coverage'
  elements: string[]
  detail: string
}

const GEOMETRY_EPSILON = 0.5

function intersects(a: LayoutElement, b: LayoutElement): boolean {
  return a.left < b.right - GEOMETRY_EPSILON && a.right > b.left + GEOMETRY_EPSILON &&
    a.top < b.bottom - GEOMETRY_EPSILON && a.bottom > b.top + GEOMETRY_EPSILON
}

export function evaluateLayoutSnapshot(snapshot: LayoutSnapshot): { issues: LayoutIssue[] } {
  const issues: LayoutIssue[] = []
  if (snapshot.horizontalScroll > 0) {
    issues.push({ kind: 'horizontal_scroll', elements: [], detail: `horizontal scroll=${snapshot.horizontalScroll}` })
  }
  for (const element of snapshot.elements) {
    if (element.left < -GEOMETRY_EPSILON || element.top < -GEOMETRY_EPSILON ||
      element.right > snapshot.viewport.width + GEOMETRY_EPSILON ||
      element.bottom > snapshot.viewport.height + GEOMETRY_EPSILON) {
      issues.push({ kind: 'clipped', elements: [element.id], detail: `${element.id} exceeds viewport` })
    }
  }
  for (let i = 0; i < snapshot.elements.length; i += 1) {
    for (let j = i + 1; j < snapshot.elements.length; j += 1) {
      const a = snapshot.elements[i]!
      const b = snapshot.elements[j]!
      if (intersects(a, b)) {
        issues.push({ kind: 'overlap', elements: [a.id, b.id], detail: `${a.id} intersects ${b.id}` })
        if ((a.id === 'composer' && b.id === 'timeline') || (a.id === 'timeline' && b.id === 'composer')) {
          issues.push({ kind: 'composer_coverage', elements: [a.id, b.id], detail: 'composer covers timeline content' })
        }
      }
    }
  }
  return { issues }
}

export function approvalStormIssue(approvalCount: number): string | null {
  if (approvalCount > 12) {
    return `approval storm: ${approvalCount} one-shot dialogs; always-allow did not take effect`
  }
  return null
}

export function taskWallClockIssue(wallMs: number): string | null {
  if (wallMs > 45 * 60 * 1000) return `task wall clock ${wallMs}ms exceeds 45m hard-fail gate`
  return null
}

export function timelineKinds(items: Array<{ kind: string }>): { valid: boolean; issue: string | null } {
  const kinds = items.map((item) => item.kind)
  const prompt = kinds.indexOf('prompt')
  const final = kinds.lastIndexOf('final')
  const tool = kinds.indexOf('tool')
  const toolResult = kinds.indexOf('tool_result')
  if (prompt < 0 || tool < 0 || toolResult < 0 || final < 0) return { valid: false, issue: 'missing required timeline item' }
  if (!(prompt < tool && tool < toolResult && toolResult < final)) return { valid: false, issue: `non-chronological timeline: ${kinds.join(' > ')}` }
  return { valid: true, issue: null }
}
