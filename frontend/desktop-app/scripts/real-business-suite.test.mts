import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  buildBatchPrompts,
  buildMissingFileRepairPrompt,
  buildSpringMysqlRepairInstructions,
  parseMissingFilenames,
  selectMissingFileRepair,
  realBusinessScenarios
} from './real-business-scenarios.mts'
import {
  aggregateUsage,
  cacheHitRate,
  evaluateLayoutSnapshot,
  gameEnteredPlayableState,
  gameMenuStillBlockingPlay,
  isMeaningfulProtocolEvent,
  missingWebDeliverables,
  parseDotEnv,
  parseHudScore,
  playProbeUrl,
  mysqlPartsFromJdbc,
  companyLoginProbeIssue,
  companyWebsiteArtifactIssue,
  travelWebsiteArtifactIssue,
  marketBiArtifactIssue,
  evTcoArtifactIssue,
  rentalDecisionArtifactIssue,
  springMysqlArtifactIssue,
  findProjectLocalMaven,
  mavenTestCountsIssue,
  missingOutputDirIssue,
  staticFilePath,
  terminalOutcomeIssue,
  hasInFlightTool,
  hasInFlightRecovery,
  firstTokenHardFail,
  approvalStormIssue,
  taskWallClockIssue,
  selectJavaSwingMain,
  timelineKinds,
  webServeRoot
} from './real-business-metrics.mts'
import { screenshotPath } from './cdp-harness.mts'

test('CDP screenshots accept both artifact-relative and absolute paths', () => {
  assert.equal(
    screenshotPath('C:\\artifacts\\run', 'screenshots\\T01.png'),
    'C:\\artifacts\\run\\screenshots\\T01.png'
  )
  assert.equal(
    screenshotPath('C:\\artifacts\\run', 'D:\\evidence\\T01.png'),
    'D:\\evidence\\T01.png'
  )
})

test('real business suite defines nine complete user scenarios', () => {
  assert.equal(realBusinessScenarios.length, 9)
  assert.equal(new Set(realBusinessScenarios.map((scenario) => scenario.id)).size, 9)
  for (const scenario of realBusinessScenarios) {
    assert.ok(scenario.prompt.length > 500, `${scenario.id} prompt is too short`)
    assert.equal(scenario.prompt.includes('\uFFFD'), false, `${scenario.id} prompt contains replacement characters`)
    assert.equal(scenario.prompt.includes('\uFFFD'), false, `${scenario.id} prompt contains replacement characters`)
    assert.ok(scenario.outputDir.startsWith(scenario.id), `${scenario.id} output dir is not isolated`)
    assert.ok(scenario.expectedTools.length >= 2, `${scenario.id} lacks tool expectations`)
    assert.ok(scenario.visualCheckpoints.length >= 2, `${scenario.id} lacks visual checkpoints`)
    assert.equal(scenario.maxInputTokens, 200_000)
    assert.equal(scenario.maxOutputTokens, 48_000)
    assert.equal(scenario.timeoutMs, 45 * 60 * 1000)
  }
})

test('real business prompts preserve the required implementation boundaries', () => {
  const byId = Object.fromEntries(realBusinessScenarios.map((scenario) => [scenario.id, scenario.prompt]))
  assert.match(byId.T01, /localStorage|HTML|JavaScript|T01-runner/)
  assert.match(byId.T01, /write tool|TEST-REPORT/)
  assert.match(byId.T01, /http\.server/)
  assert.match(byId.T02, /HTML|JavaScript|T02-platformer|two|T02/)
  assert.match(byId.T02, /README.md|TEST-REPORT/)
  assert.match(byId.T02, /Playable-game contract|#stateLabel|#score/)
  assert.match(byId.T02, /Identifier has already been declared|TILE/)
  assert.match(byId.T02, /http\.server/)
  assert.match(byId.T03, /websearch|webfetch|Skill|T03-company/)
  assert.match(byId.T03, /skill tool|Do not call download_skill/)
  assert.match(byId.T03, /Java, Spring, Maven, or a backend substitute is a hard failure/)
  assert.match(byId.T03, /http\.server/)
  assert.match(byId.T03, /admin\.html/)
  assert.match(byId.T03, /#btn-demo-login must immediately navigate/)
  assert.match(byId.T03, /immediately write README.md and TEST-REPORT.md/)
  assert.match(byId.T03, /next tool call must be write of T03-company\/PLAN.md/)
  assert.match(byId.T04, /datetime|3000|T04-travel|sources/)
  assert.match(byId.T05, /Java 17|Swing|javac|T05-number-bomb/)
  assert.match(byId.T06, /CSV|BI|T06-market-bi|websearch/)
  assert.match(byId.T06, /Do not probe pandas/)
  assert.match(byId.T06, /Do not write _probe\.py/)
  assert.match(byId.T06, /no CDN/)
  assert.match(byId.T06, /Do not call workflow/)
  assert.match(byId.T06, /At least one \.csv file must exist/)
  assert.match(byId.T06, /webfetch returns 403/)
  assert.match(byId.T06, /literal <select>|static table-only snapshot/)
  assert.match(byId.T06, /Do not call download_file/)
  assert.match(byId.T07, /TCO|T07-ev|websearch/)
  assert.match(byId.T07, /Do not probe pandas/)
  assert.match(byId.T07, /Do not write _probe\.py/)
  assert.match(byId.T07, /Do not call workflow/)
  assert.match(byId.T07, /no CDN/)
  assert.match(byId.T07, /Close every non-void HTML tag/)
  assert.match(byId.T08, /3500|60|T08-rental|websearch/)
  assert.match(byId.T08, /Do not probe pandas/)
  assert.match(byId.T08, /Do not write _probe\.py/)
  assert.match(byId.T08, /Do not call workflow/)
  assert.match(byId.T08, /no CDN/)
  assert.match(byId.T08, /Java, Spring, Maven/)
  assert.match(byId.T08, /合同与风险/)
  assert.match(byId.T08, /inline SVG map|the word 地图/)
  assert.match(byId.T08, /areas\.csv/)
  assert.match(byId.T09, /Spring Boot 4.1.0|Maven 3.9.16|MySQL 8|Flyway/)
  assert.match(byId.T09, /first tool call must be write of T09-coffee\/pom\.xml/)
  assert.match(byId.T09, /Do not call websearch or webfetch/)
  assert.match(byId.T09, /already injected into the process environment/)
  assert.match(byId.T09, /Python, Flask, Django, or SQLite substitute is a hard failure/)
  assert.match(byId.T09, /write tool first|src\/main\/java/)
  assert.match(byId.T09, /skeleton is a hard failure|@RestController/)
  assert.match(byId.T09, /待填写/)
  assert.match(byId.T09, /待验证/)
  assert.match(byId.T09, /Tests run: N/)
  assert.match(byId.T09, /Failures: 0, Errors: 0/)
  assert.match(byId.T09, /Listing MIGRATION-ROLLBACK\.md or TEST-REPORT\.md in README does not create them/)
  assert.match(byId.T09, /do not wait for Maven download/)
  assert.match(byId.T09, /do not rename or relocate/)
  assert.match(byId.T09, /BigDecimal/)
  assert.match(byId.T09, /webmvc\.test\.autoconfigure/)
  assert.match(byId.T09, /DaoAuthenticationProvider/)
  assert.match(byId.T09, /cannot start with ROLE_/)
  assert.match(byId.T09, /flyway-maven-plugin/)
  assert.match(byId.T09, /download-only mvnw/)
  assert.match(byId.T09, /hardcode a datasource password/)
  assert.match(byId.T09, /@SpringBootTest/)
  assert.match(byId.T09, /ApplicationRunner|@DependsOn\("flyway"\)/)
  assert.match(byId.T09, /starter-flyway/)
  assert.match(byId.T09, /flyway-mysql|baseline-on-migrate/)
  assert.match(byId.T09, /static\/index\.html/)
  assert.match(byId.T09, /ProductService\.java/)
  assert.match(byId.T09, /T09-coffee with a hyphen|T09_coffee is a hard failure/)
  assert.match(byId.T09, /_probe/)
})

test('missing-file repair prompt writes documents instead of re-reading source', () => {
  assert.deepEqual(
    parseMissingFilenames('web artifact is incomplete; missing README.md, TEST-REPORT.md'),
    ['README.md', 'TEST-REPORT.md']
  )
  const prompt = buildMissingFileRepairPrompt('T02-platformer', ['README.md', 'TEST-REPORT.md'])
  assert.match(prompt, /T02-platformer\/README\.md/)
  assert.match(prompt, /T02-platformer\/TEST-REPORT\.md/)
  assert.match(prompt, /write tool/)
  assert.match(prompt, /Do not read existing/)
  assert.doesNotMatch(prompt, /Inspect every file/)
  assert.doesNotMatch(prompt, /play the page/)
  const t06Repair = buildMissingFileRepairPrompt('T06-market-bi', ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'data.csv'])
  assert.match(t06Repair, /literal <select>/)
  assert.match(t06Repair, /static table snapshot/)
  assert.deepEqual(
    selectMissingFileRepair('T03', 'web artifact is incomplete; missing README.md, TEST-REPORT.md', ['index.html', 'PLAN.md', 'login.html']),
    ['README.md', 'TEST-REPORT.md', 'admin.html']
  )
  assert.deepEqual(
    selectMissingFileRepair('T03', 'web artifact is incomplete; missing index.html, README.md', []),
    []
  )
  assert.deepEqual(
    selectMissingFileRepair('T03', 'company website is incomplete; missing admin.html', ['index.html', 'README.md']),
    ['admin.html']
  )
  assert.deepEqual(
    selectMissingFileRepair('T03', 'web artifact is incomplete; missing README.md, TEST-REPORT.md', ['index.html', 'admin.html', 'PLAN.md']),
    ['README.md', 'TEST-REPORT.md']
  )
  assert.deepEqual(
    selectMissingFileRepair('T03', 'company website has no demo login control (#btn-demo-login)', ['index.html', 'admin.html', 'PLAN.md']),
    []
  )
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'spring-mysql Boot 4 AutoConfigureMockMvc is org.springframework.boot.webmvc.test.autoconfigure, not org.springframework.boot.test.autoconfigure.web.servlet',
      ['pom.xml', 'src/test/java/com/rxycode/t09coffee/CoffeeShopApplicationTests.java']
    ),
    []
  )
  const adminRepair = buildMissingFileRepairPrompt('T03-company', ['README.md', 'TEST-REPORT.md', 'admin.html'])
  assert.match(adminRepair, /T03-company\/admin\.html/)
  assert.match(adminRepair, /用户管理/)
  assert.match(adminRepair, /Do not rewrite index\.html/)
  assert.deepEqual(
    selectMissingFileRepair('T04', 'web artifact is incomplete; missing index.html, README.md, TEST-REPORT.md', []),
    []
  )
  assert.deepEqual(
    selectMissingFileRepair('T04', 'travel website is incomplete; missing PLAN.md, sources.md', ['index.html', 'README.md']),
    ['PLAN.md', 'sources.md']
  )
  assert.deepEqual(
    selectMissingFileRepair(
      'T08',
      'rental decision website is incomplete; missing data CSV',
      ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md']
    ),
    ['areas.csv']
  )
  assert.deepEqual(
    selectMissingFileRepair(
      'T06',
      'market BI website is incomplete; missing data CSV',
      ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md']
    ),
    ['data.csv']
  )
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'spring-mysql artifact is incomplete; missing README.md, DEVELOPMENT.md, TEST-REPORT.md',
      ['src/main/java/com/rxycode/t09coffee/web/AuthController.java', 'pom.xml']
    ),
    ['README.md', 'DEVELOPMENT.md', 'TEST-REPORT.md']
  )
  assert.deepEqual(
    parseMissingFilenames('spring-mysql pom is missing spring-boot-starter-flyway; Boot 4 does not auto-run flyway-core alone'),
    []
  )
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'spring-mysql pom.xml must declare spring-boot-starter-flyway; Boot 4 does not auto-run flyway-core alone',
      ['pom.xml', 'src/main/java/com/example/coffee/controller/AuthController.java']
    ),
    []
  )
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'mvn test failed:\nhas no real Maven test counts\nDownloading Maven 3.9.16',
      ['pom.xml', 'src/main/java/com/example/coffee/controller/AuthController.java', 'TEST-REPORT.md']
    ),
    []
  )
  assert.equal(
    findProjectLocalMaven(['mvnw.cmd', '.tools/apache-maven-3.9.16/bin/mvn.cmd']),
    '.tools/apache-maven-3.9.16/bin/mvn.cmd'
  )
  assert.deepEqual(
    parseMissingFilenames('spring-mysql artifact has no src/test/java *Test.java'),
    ['src/test/java/com/rxycode/t09coffee/CoffeeApplicationTest.java']
  )
  assert.deepEqual(
    parseMissingFilenames('spring-mysql artifact is incomplete; missing TEST-REPORT.md; harness mvn test observed: Tests run: 2, Failures: 0'),
    ['TEST-REPORT.md']
  )
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'spring-mysql artifact is incomplete; missing README.md, DEVELOPMENT.md, API.md, ARCHITECTURE.md, SECURITY.md, MIGRATION-ROLLBACK.md, TEST-REPORT.md; harness mvn test observed: Tests run: 2, Failures: 0',
      ['src/main/java/com/example/t09coffee/controller/AuthController.java']
    ),
    ['README.md', 'DEVELOPMENT.md', 'API.md', 'ARCHITECTURE.md', 'SECURITY.md', 'MIGRATION-ROLLBACK.md', 'TEST-REPORT.md']
  )
  const reportRepair = buildSpringMysqlRepairInstructions('spring-mysql TEST-REPORT.md has no real Maven test counts')
  assert.match(reportRepair, /Do not rewrite Java/)
  assert.match(reportRepair, /Tests run: N/)
  assert.match(reportRepair, /You must call bash/)
  assert.match(reportRepair, /待验证/)
  assert.doesNotMatch(reportRepair, /t09coffee\/web\/AuthController/)
  const flywayRepair = buildSpringMysqlRepairInstructions('spring-mysql pom.xml must declare spring-boot-starter-flyway; Boot 4 does not auto-run flyway-core alone')
  assert.match(flywayRepair, /Edit pom\.xml/)
  assert.doesNotMatch(flywayRepair, /Call the write tool once for each path/)
  const controllerRepair = buildSpringMysqlRepairInstructions('spring-mysql artifact has no *Controller.java REST layer')
  assert.match(controllerRepair, /any package/)
  assert.match(controllerRepair, /do not start a second tree/)
  assert.doesNotMatch(controllerRepair, /t09coffee\/web\/AuthController/)
  const compileRepair = buildSpringMysqlRepairInstructions('mvn test failed:\n[ERROR] InventoryController.java:[75,49] incompatible types: double cannot be converted to java.lang.Integer')
  assert.match(compileRepair, /BigDecimal/)
  assert.match(compileRepair, /Edit only the files named/)
  assert.match(compileRepair, /orElseThrow belongs on Optional/)
  assert.match(compileRepair, /Product\.getInventory|InventoryRepository/)
  assert.match(compileRepair, /DaoAuthenticationProvider\(userDetailsService\)/)
  assert.match(compileRepair, /ApplicationRunner|@DependsOn\("flyway"\)/)
  assert.match(compileRepair, /starter-flyway/)
  assert.match(compileRepair, /baseline-on-migrate/)
  assert.match(compileRepair, /MockHttpSession/)
  assert.match(compileRepair, /cannot start with ROLE_|roles\(\)/)
  assert.match(compileRepair, /csrf\.disable|ignoringRequestMatchers|was:<403>/)
  assert.match(compileRepair, /was:<401>|ProviderManager|getRequest\(\)\.getSession/)
  assert.match(compileRepair, /was:<400>|BadCredentialsException|barista/)
  assert.match(compileRepair, /flyway-maven-plugin|PluginContainerException/)
  assert.match(compileRepair, /checksum mismatch|ddl-auto|non-empty schema/)
  assert.match(compileRepair, /mockMvc\.perform|contextLoads/)
  assert.match(compileRepair, /lambda 表达式引用的本地变量必须是最终变量/)
  assert.match(compileRepair, /executeQuery|GeneratedKeyHolder|LAST_INSERT_ID/)
  assert.match(compileRepair, /was:<500>|updatedAt|DATETIME NOT NULL/)
  assert.match(compileRepair, /SpringBootConfiguration|same package/)
  assert.match(compileRepair, /write-dates-as-timestamps|WRITE_DATES_AS_TIMESTAMPS/)
  assert.match(compileRepair, /tools\.jackson\.databind/)
  assert.doesNotMatch(compileRepair, /add com\.fasterxml\.jackson\.core:jackson-databind/)
  assert.doesNotMatch(compileRepair, /t09coffee\/web\/AuthController/)
  const jacksonRepair = buildSpringMysqlRepairInstructions('spring-mysql Boot 4 Jackson 3 cannot bind spring.jackson.serialization.write-dates-as-timestamps; delete that key or use WRITE_DATES_AS_TIMESTAMPS')
  assert.match(jacksonRepair, /WRITE_DATES_AS_TIMESTAMPS/)
  assert.match(jacksonRepair, /[Dd]elete spring\.jackson\.serialization.write-dates-as-timestamps/)
  const fasterxmlRepair = buildSpringMysqlRepairInstructions('spring-mysql Boot 4 cannot import com.fasterxml.jackson.databind; use tools.jackson.databind or jsonPath')
  assert.match(fasterxmlRepair, /tools\.jackson\.databind/)
  assert.match(fasterxmlRepair, /jsonPath/)
  const webmvcPkgRepair = buildSpringMysqlRepairInstructions('spring-mysql Boot 4 AutoConfigureMockMvc is org.springframework.boot.webmvc.test.autoconfigure, not org.springframework.boot.test.autoconfigure.webmvc')
  assert.match(webmvcPkgRepair, /webmvc\.test\.autoconfigure/)
  const bootCfgRepair = buildSpringMysqlRepairInstructions('spring-mysql *Test.java package cannot find @SpringBootConfiguration; put tests in the application package or set @SpringBootTest(classes=...)')
  assert.match(bootCfgRepair, /same package|classes=/)
  assert.match(bootCfgRepair, /\$\.token|form username/)
  assert.match(bootCfgRepair, /Delete ONLY|do not delete every/i)
  assert.match(bootCfgRepair, /Tests\.java is a valid filename/)
  const missingTestRepair = buildSpringMysqlRepairInstructions('spring-mysql artifact has no src/test/java *Test.java')
  assert.match(missingTestRepair, /CoffeeApplicationTests\.java already exists/)
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'spring-mysql artifact has no src/test/java *Test.java',
      ['src/test/java/com/rxycode/t09/coffee/CoffeeApplicationTests.java']
    ),
    []
  )
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'spring-mysql artifact has no src/test/java *Test.java',
      ['src/main/java/com/rxycode/t09/coffee/CoffeeApplication.java']
    ),
    ['src/test/java/com/rxycode/t09/coffee/CoffeeApplicationTests.java']
  )
  const h2Repair = buildSpringMysqlRepairInstructions('spring-mysql tests substituted H2/SQLite for MySQL 8')
  assert.match(h2Repair, /Delete the H2|SPRING_DATASOURCE_|src\/test\/resources\/application\.yml/)
  assert.doesNotMatch(h2Repair, /Call the write tool once for each path/)
  const h2DriverRepair = buildSpringMysqlRepairInstructions('mvn test failed:\nCannot load driver class: org.h2.Driver')
  assert.match(h2DriverRepair, /src\/test\/resources\/application\.yml/)
  assert.doesNotMatch(h2DriverRepair, /orElseThrow belongs on Optional/)
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'spring-mysql tests substituted H2/SQLite for MySQL 8',
      ['pom.xml', 'src/test/resources/application.yml', 'src/main/java/com/coffee/controller/AuthController.java']
    ),
    ['src/test/resources/application.yml']
  )
  const h2Write = buildMissingFileRepairPrompt('T09-coffee', ['src/test/resources/application.yml'], 'spring-mysql tests substituted H2/SQLite for MySQL 8')
  assert.match(h2Write, /SPRING_DATASOURCE_URL/)
  assert.match(h2Write, /org\.h2\.Driver/)
  const classLoadRepair = buildSpringMysqlRepairInstructions('spring-mysql tests do not start Spring or MockMvc; a class-load or empty contextLoads smoke is not enough')
  assert.match(classLoadRepair, /@SpringBootTest/)
  assert.match(classLoadRepair, /getSimpleName/)
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'spring-mysql tests do not start Spring or MockMvc; a class-load or empty contextLoads smoke is not enough',
      ['src/main/java/com/coffee/controller/AuthController.java', 'src/test/java/com/rxycode/t09coffee/CoffeeApplicationTest.java']
    ),
    ['src/test/java/com/rxycode/t09coffee/CoffeeApplicationTest.java']
  )
  const testWrite = buildMissingFileRepairPrompt('T09-coffee', ['src/test/java/com/rxycode/t09coffee/CoffeeApplicationTest.java'])
  assert.match(testWrite, /mockMvc\.perform/)
  assert.match(testWrite, /AutoConfigureMockMvc/)
  const mockMvcRepair = buildSpringMysqlRepairInstructions('mvn test failed:\n[ERROR] 程序包org.springframework.boot.test.autoconfigure.web.servlet不存在')
  assert.match(mockMvcRepair, /spring-boot-starter-webmvc-test/)
  assert.match(mockMvcRepair, /webmvc\.test\.autoconfigure/)
  const hyphenRepair = buildSpringMysqlRepairInstructions('wrote T09_coffee instead of T09-coffee; hyphen directory is required')
  assert.match(hyphenRepair, /T09-coffee with a hyphen/)
  assert.match(hyphenRepair, /Do not probe MySQL/)
  assert.ok(
    selectMissingFileRepair('T09', 'spring-mysql artifact has no .java source', ['README.md', 'TEST-REPORT.md']).includes('pom.xml')
  )
  assert.ok(
    selectMissingFileRepair('T09', 'output directory was not created', []).includes('src/main/java/com/coffee/controller/AuthController.java')
  )
  assert.equal(missingOutputDirIssue('T09-coffee', false, true), 'wrote T09_coffee instead of T09-coffee; hyphen directory is required')
  assert.equal(missingOutputDirIssue('T09-coffee', true, true), null)
  assert.equal(missingOutputDirIssue('T09-coffee', false, false), 'output directory was not created')
  const htmlRepair = buildSpringMysqlRepairInstructions('spring-mysql artifact has no static frontend HTML')
  assert.match(htmlRepair, /static\/index\.html/)
  assert.match(htmlRepair, /Do not rewrite Java/)
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'spring-mysql artifact has no *Controller.java REST layer',
      ['pom.xml', 'src/main/java/com/coffee/CoffeeApplication.java']
    ),
    [
      'src/main/java/com/coffee/controller/AuthController.java',
      'src/main/java/com/coffee/controller/ProductController.java',
      'src/main/java/com/coffee/controller/InventoryController.java',
      'src/main/java/com/coffee/controller/OrderController.java',
      'src/main/java/com/coffee/controller/RevenueController.java',
      'src/main/resources/static/index.html',
      'src/main/resources/db/migration/V1__init.sql',
      'src/test/java/com/coffee/CoffeeApplicationTests.java'
    ]
  )
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'spring-mysql artifact has no static frontend HTML',
      ['src/main/java/com/coffee/controller/AuthController.java', 'pom.xml']
    ),
    ['src/main/resources/static/index.html']
  )
  const staticWrite = buildMissingFileRepairPrompt('T09-coffee', ['src/main/resources/static/index.html'])
  assert.match(staticWrite, /T09-coffee\/src\/main\/resources\/static\/index\.html/)
  assert.match(staticWrite, /closed HTML page/)
  assert.match(staticWrite, /No CDN/)
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'spring-mysql TEST-REPORT.md has no real Maven test counts; harness mvn test observed: Tests run: 4, Failures: 0, Errors: 0',
      ['src/main/java/com/coffee/controller/AuthController.java', 'TEST-REPORT.md']
    ),
    ['TEST-REPORT.md']
  )
  const countWrite = buildMissingFileRepairPrompt(
    'T09-coffee',
    ['TEST-REPORT.md'],
    'spring-mysql TEST-REPORT.md has no real Maven test counts; harness mvn test observed: Tests run: 4, Failures: 0, Errors: 0'
  )
  assert.match(countWrite, /Tests run: 4/)
  assert.match(countWrite, /Copy this observed line/)
  const failingCopy = buildMissingFileRepairPrompt(
    'T09-coffee',
    ['TEST-REPORT.md'],
    'spring-mysql TEST-REPORT.md records Failures: 0, Errors: 2; harness mvn test observed: Tests run: 2, Failures: 0, Errors: 2'
  )
  assert.doesNotMatch(failingCopy, /Copy this observed line/)
  assert.match(failingCopy, /Failures: 0, Errors: 0/)
})

test('batch prompt builder gives one isolated run and one ordered long-session run', () => {
  const prompts = buildBatchPrompts()
  assert.equal(prompts.independent.length, 9)
  assert.equal(prompts.sequential.length, 9)
  assert.deepEqual(prompts.sequential.map((item) => item.id), realBusinessScenarios.map((item) => item.id))
  assert.ok(prompts.independent.every((item) => item.prompt.includes(item.outputDir)))
  assert.ok(prompts.sequential.every((item) => item.prompt.includes(item.outputDir)))
})

test('usage aggregation keeps null unreported values and uses input as cache denominator', () => {
  const summary = aggregateUsage([
    { input_tokens: 1000, output_tokens: 200, cache_hit_tokens: 700, cache_miss_tokens: 300, reporting_status: 'reported' },
    { input_tokens: null, output_tokens: null, cache_hit_tokens: null, cache_miss_tokens: null, reporting_status: 'not_reported' },
    { input_tokens: 500, output_tokens: 100, cache_hit_tokens: 100, cache_miss_tokens: 400, reporting_status: 'partial' }
  ])
  assert.equal(summary.input_tokens, 1500)
  assert.equal(summary.output_tokens, 300)
  assert.equal(summary.cache_hit_tokens, 800)
  assert.equal(summary.cache_miss_tokens, 700)
  assert.equal(summary.total_tokens, 1800)
  assert.equal(summary.reporting_status, 'partial')
  assert.equal(cacheHitRate(summary), 800 / 1500)
})

test('usage aggregation does not turn entirely unknown provider metrics into zero', () => {
  const summary = aggregateUsage([
    { input_tokens: null, output_tokens: null, cache_hit_tokens: null, cache_miss_tokens: null, reporting_status: 'not_reported' }
  ])
  assert.equal(summary.input_tokens, null)
  assert.equal(summary.output_tokens, null)
  assert.equal(summary.cache_hit_tokens, null)
  assert.equal(summary.cache_miss_tokens, null)
  assert.equal(summary.total_tokens, null)
  assert.equal(cacheHitRate(summary), null)
})

test('desktop geometry contract keeps the transcript above a fixed composer', () => {
  const css = readFileSync(new URL('../src/renderer/src/assets/main.css', import.meta.url), 'utf8')
  assert.match(css, /\.task-main \{\s*display: flex;\s*flex-direction: column;\s*min-height: 0;\s*overflow: hidden;/)
  assert.match(css, /\.chat-area \{\s*min-height: 0;\s*flex: 1 1 auto;\s*overflow: auto;/)
  assert.match(
    css,
    /\.composer \{\s*flex: 0 0 auto;\s*min-height: 0;[\s\S]*?position: relative;[\s\S]*?z-index:\s*\d+;/
  )
})

test('successful GUI runs must expose a non-empty Final Answer', () => {
  assert.equal(terminalOutcomeIssue('succeeded', ''), 'succeeded task has no non-empty Final Answer')
  assert.equal(terminalOutcomeIssue('succeeded', 'Done'), null)
  assert.equal(terminalOutcomeIssue('queued', ''), 'GUI session ended as queued without a Final Answer')
  assert.match(String(terminalOutcomeIssue('failed', '')), /ended as failed/)
  assert.match(String(terminalOutcomeIssue('failed', 'tool_calls mismatch')), /GUI session failed/)
  assert.equal(
    terminalOutcomeIssue('failed', '[evidence failed: Tool write did not complete: failed]', true),
    null
  )
  assert.match(
    String(terminalOutcomeIssue('failed', '[evidence failed: Tool write did not complete: failed]', false)),
    /GUI session failed/
  )
  assert.equal(
    terminalOutcomeIssue(
      'failed',
      '[error] FirstTokenTimeoutError: provider produced no first response event before the deadline',
      true
    ),
    null
  )
})

test('web artifacts cannot pass with only an index.html', () => {
  assert.deepEqual(missingWebDeliverables(['index.html', 'game.js', 'styles.css', 'PLAN.md']), ['README.md', 'TEST-REPORT.md'])
  assert.deepEqual(missingWebDeliverables(['index.html', 'README.md', 'TEST-REPORT.md']), [])
})

test('company website stubs and Java substitutes cannot pass T03 smoke', () => {
  assert.match(
    String(companyWebsiteArtifactIssue(['index.html', 'README.md', 'TEST-REPORT.md'])),
    /PLAN\.md/
  )
  assert.match(
    String(companyWebsiteArtifactIssue(['index.html', 'PLAN.md', 'README.md', 'TEST-REPORT.md', 'pom.xml'])),
    /Java\/Spring\/Maven/
  )
  const stub = {
    'index.html': '<html><body><h1>部门管理</h1><button onclick="addEmployee()">新增员工</button></body></html>'
  }
  assert.match(
    String(companyWebsiteArtifactIssue(
      ['index.html', 'PLAN.md', 'README.md', 'TEST-REPORT.md'],
      (rel) => stub[rel] ?? ''
    )),
    /admin\.html|demo login|#btn-demo-login/
  )
  const complete = {
    'index.html': '<button id="btn-open-login">登录</button><button id="btn-demo-login">演示登录</button><a href="#products">产品</a><a href="#team">团队</a><a href="#cases">案例</a><a href="#contact">联系</a>',
    'admin.html': '<nav>用户管理 订单管理 内容管理 设置 数据看板</nav>',
    'admin.js': 'localStorage.setItem("t03", "1"); document.body.innerHTML = "用户管理 订单管理 内容管理 设置 数据看板";'
  }
  assert.equal(
    companyWebsiteArtifactIssue(
      ['index.html', 'admin.html', 'admin.js', 'PLAN.md', 'README.md', 'TEST-REPORT.md'],
      (rel) => complete[rel] ?? ''
    ),
    null
  )
  assert.match(
    String(companyWebsiteArtifactIssue(
      ['index.html', 'admin.js', 'PLAN.md', 'README.md', 'TEST-REPORT.md'],
      (rel) => complete[rel] ?? ''
    )),
    /admin\.html/
  )
  const nested = {
    'public/index.html': '<a class="btn-login" href="login.html">登录</a><a href="products.html">产品</a><a href="team.html">团队</a><a href="cases.html">案例</a><a href="contact.html">联系</a>',
    'public/login.html': '<form id="loginForm"><input id="loginUsername"><input id="loginPassword" type="password"><button type="submit" id="btn-open-login">登录</button></form><button id="btn-demo-login">演示登录</button>',
    'public/admin.html': '<button>用户管理</button><button>订单管理</button><button>内容管理</button><button>站点设置</button><button>数据分析</button>',
    'public/js/data.js': 'localStorage.setItem("t03", "1");'
  }
  assert.equal(
    companyWebsiteArtifactIssue(
      ['PLAN.md', 'README.md', 'TEST-REPORT.md', 'public/index.html', 'public/login.html', 'public/admin.html', 'public/js/data.js'],
      (rel) => nested[rel] ?? ''
    ),
    null
  )
  assert.match(
    String(companyLoginProbeIssue({ ok: true, demoClicked: false, textLength: 148, title: 'T03 公司业务系统' })),
    /demo login/
  )
  assert.equal(
    companyLoginProbeIssue({
      demoClicked: true,
      adminModules: 5,
      adminText: '用户管理 订单管理 内容管理 设置 数据看板'
    }),
    null
  )
})

test('travel website stubs cannot pass T04 smoke', () => {
  assert.match(
    String(travelWebsiteArtifactIssue(['index.html', 'README.md', 'TEST-REPORT.md'])),
    /PLAN\.md|sources\.md/
  )
  assert.match(
    String(travelWebsiteArtifactIssue(['index.html', 'PLAN.md', 'README.md', 'TEST-REPORT.md', 'sources.md'])),
    /budget CSV/
  )
  const stub = {
    'index.html': '<html><body><h1>苏杭五日</h1><p>广州出发，预算 3000，Day 1 苏州，杭州，含妆造。</p></body></html>'
  }
  assert.match(
    String(travelWebsiteArtifactIssue(
      ['index.html', 'PLAN.md', 'README.md', 'TEST-REPORT.md', 'sources.md', 'budget.csv'],
      (rel) => stub[rel] ?? ''
    )),
    /rain plan|alternatives|interactive/
  )
  const complete = {
    'index.html': '<select id="city"><option>苏州</option><option>杭州</option></select><p>广州往返，预算 3000。Day 1 苏州。雨天预案与备选路线。妆造一次。</p>'
  }
  assert.equal(
    travelWebsiteArtifactIssue(
      ['index.html', 'PLAN.md', 'README.md', 'TEST-REPORT.md', 'sources.md', 'budget.csv'],
      (rel) => complete[rel] ?? ''
    ),
    null
  )
})

test('first-token hard fail requires no visible work in the first 30s', () => {
  assert.equal(firstTokenHardFail(345_512, 26), false)
  assert.equal(firstTokenHardFail(31_000, 31_000), true)
  assert.equal(firstTokenHardFail(31_000, null), true)
  assert.equal(firstTokenHardFail(19_000, 26), false)
})

test('market BI stubs cannot pass T06 smoke', () => {
  assert.match(
    String(marketBiArtifactIssue(['index.html', 'README.md', 'TEST-REPORT.md'])),
    /sources\.md/
  )
  const stub = {
    'index.html': '<html><body><p>gold silver nasdaq</p></body></html>'
  }
  assert.match(
    String(marketBiArtifactIssue(
      ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'data.csv'],
      (rel) => stub[rel] ?? ''
    )),
    /risk disclaimer|interactive/
  )
  const complete = {
    'index.html': '<select id="asset"><option>黄金</option><option>白银</option><option>Nasdaq</option><option>S&P 500</option></select><p>风险披露：非投资建议。</p>'
  }
  assert.equal(
    marketBiArtifactIssue(
      ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'prices.csv'],
      (rel) => complete[rel] ?? ''
    ),
    null
  )
  const cdn = {
    'index.html': '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script><select id="asset"><option>黄金</option><option>白银</option><option>Nasdaq</option><option>S&P 500</option></select><p>风险披露：非投资建议。</p>'
  }
  assert.match(
    String(marketBiArtifactIssue(
      ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'prices.csv'],
      (rel) => cdn[rel] ?? ''
    )),
    /CDN/
  )
})

test('EV TCO stubs cannot pass T07 smoke', () => {
  assert.match(
    String(evTcoArtifactIssue(['index.html', 'README.md', 'TEST-REPORT.md'])),
    /sources\.md/
  )
  const stub = {
    'index.html': '<html><body><p>广州 五年 TCO 150000</p></body></html>'
  }
  assert.match(
    String(evTcoArtifactIssue(
      ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'tco.csv'],
      (rel) => stub[rel] ?? ''
    )),
    /mileage|weights|risk|interactive/
  )
  const complete = {
    'index.html': '<input id="budget"><input id="mileage"><select id="weight"><option>价格权重</option></select><p>广州三口之家，预算 150000-250000，五年 TCO，里程可调。风险：价格区间不确定。</p>'
  }
  assert.equal(
    evTcoArtifactIssue(
      ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'tco.csv'],
      (rel) => complete[rel] ?? ''
    ),
    null
  )
  const cdn = {
    'index.html': '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script><input id="budget"><input id="mileage"><select id="weight"><option>价格权重</option></select><p>广州三口之家，预算 150000-250000，五年 TCO，里程可调。风险：价格区间不确定。</p>'
  }
  assert.match(
    String(evTcoArtifactIssue(
      ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'tco.csv'],
      (rel) => cdn[rel] ?? ''
    )),
    /CDN/
  )
})

test('rental decision stubs cannot pass T08 smoke', () => {
  assert.match(
    String(rentalDecisionArtifactIssue(['index.html', 'README.md', 'TEST-REPORT.md'])),
    /sources\.md/
  )
  const stub = {
    'index.html': '<html><body><p>珠江新城 3500 60</p></body></html>'
  }
  assert.match(
    String(rentalDecisionArtifactIssue(
      ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'areas.csv'],
      (rel) => stub[rel] ?? ''
    )),
    /calendar|map|contract|weights|interactive/
  )
  const complete = {
    'index.html': '<select id="area"></select><input id="weight"><p>珠江新城通勤，租金 3500，单程 60 分钟。搬家日历与入住清单。示意图 map。合同与噪音风险。权重可调。</p>'
  }
  assert.equal(
    rentalDecisionArtifactIssue(
      ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'areas.csv'],
      (rel) => complete[rel] ?? ''
    ),
    null
  )
  const split = {
    'index.html': '<select id="area"></select><input id="weight"><p>珠江新城通勤，租金 3500，单程 60 分钟。搬家日历与入住清单。示意图 map。权重可调。噪音。</p>',
    'index.js': 'checklist.push("核对合同：租期、提前退租、维修责任");'
  }
  assert.equal(
    rentalDecisionArtifactIssue(
      ['index.html', 'index.js', 'README.md', 'TEST-REPORT.md', 'sources.md', 'areas.csv'],
      (rel) => split[rel] ?? ''
    ),
    null
  )
  assert.match(
    String(rentalDecisionArtifactIssue(
      ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'areas.csv', 'pom.xml', 'App.java'],
      (rel) => complete[rel] ?? ''
    )),
    /Java\/Spring/
  )
  const cdn = {
    'index.html': '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script><select id="area"></select><input id="weight"><p>珠江新城通勤，租金 3500，单程 60 分钟。搬家日历与入住清单。示意图 map。合同与噪音风险。权重可调。</p>'
  }
  assert.match(
    String(rentalDecisionArtifactIssue(
      ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'areas.csv'],
      (rel) => cdn[rel] ?? ''
    )),
    /CDN/
  )
})

test('spring-mysql artifacts reject a Python substitute', () => {
  const docs = [
    'README.md',
    'DEVELOPMENT.md',
    'API.md',
    'ARCHITECTURE.md',
    'SECURITY.md',
    'MIGRATION-ROLLBACK.md',
    'TEST-REPORT.md'
  ]
  assert.match(
    String(springMysqlArtifactIssue(['app.py', 'README.md', 'test_smoke.py'])),
    /Python\/SQLite/
  )
  assert.match(
    String(springMysqlArtifactIssue(['pom.xml', 'src/main/java/App.java'])),
    /Controller|skeleton|no \.java|no pom/
  )
  assert.match(
    String(springMysqlArtifactIssue(['pom.xml', 'src/main/java/App.java', ...docs])),
    /Controller|skeleton/
  )
  const complete = [
    'pom.xml',
    'mvnw.cmd',
    'src/main/java/com/rxycode/t09coffee/CoffeeShopApplication.java',
    'src/main/java/com/rxycode/t09coffee/model/Product.java',
    'src/main/java/com/rxycode/t09coffee/model/Order.java',
    'src/main/java/com/rxycode/t09coffee/web/AuthController.java',
    'src/main/java/com/rxycode/t09coffee/web/ProductController.java',
    'src/main/resources/db/migration/V1__init.sql',
    'src/main/resources/static/index.html',
    'src/main/resources/application.yml',
    'src/test/java/com/rxycode/t09coffee/CoffeeShopApplicationTest.java',
    ...docs
  ]
  const contents: Record<string, string> = {
    'src/main/java/com/rxycode/t09coffee/web/AuthController.java': '@RestController class AuthController {}',
    'src/main/java/com/rxycode/t09coffee/web/ProductController.java': '@RestController class ProductController {}',
    'src/main/resources/db/migration/V1__init.sql': 'create table users(id int); create table products(id int); create table inventory(id int); create table orders(id int); create table order_items(id int);',
    'src/main/resources/application.yml': 'spring:\n  datasource:\n    url: ${SPRING_DATASOURCE_URL}\n    username: ${SPRING_DATASOURCE_USERNAME}\n    password: ${SPRING_DATASOURCE_PASSWORD}\n',
    'src/test/java/com/rxycode/t09coffee/CoffeeShopApplicationTest.java': '@SpringBootTest @AutoConfigureMockMvc class CoffeeShopApplicationTest { MockMvc mockMvc; void api() { mockMvc.perform(get("/api/health")); } }',
    'TEST-REPORT.md': 'mvn test\nTests run: 4, Failures: 0, Errors: 0\n4 passed',
    'pom.xml': '<project><dependencies><dependency><artifactId>spring-boot-starter-flyway</artifactId></dependency></dependencies></project>'
  }
  assert.equal(
    springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? ''),
    null
  )
  assert.match(
    String(springMysqlArtifactIssue(complete, (rel) => {
      if (rel.endsWith('V1__init.sql')) {
        return 'create table menus(id int); create table users(id int); create table orders(id int); create table order_items(id int);'
      }
      return contents[rel] ?? ''
    })),
    /CREATE TABLE products|created menus/
  )
  assert.match(
    String(springMysqlArtifactIssue(complete, (rel) => {
      if (rel.endsWith('application.yml')) return `${contents[rel] ?? ''}\n    ddl-auto: validate\n`
      return contents[rel] ?? ''
    })),
    /ddl-auto=validate|use none or update/
  )
  assert.match(
    String(springMysqlArtifactIssue(complete.concat(['src/test/resources/application.yml']), (rel) => {
      if (rel.endsWith('src/test/resources/application.yml')) {
        return 'spring:\n  datasource:\n    driver-class-name: org.h2.Driver\n'
      }
      return contents[rel] ?? ''
    })),
    /H2\/SQLite/
  )
  const pluralTests = complete
    .filter((file) => file !== 'src/test/java/com/rxycode/t09coffee/CoffeeShopApplicationTest.java')
    .concat(['src/test/java/com/rxycode/t09/coffee/CoffeeApplicationTests.java'])
  assert.equal(
    springMysqlArtifactIssue(pluralTests, (rel) => {
      if (rel.endsWith('CoffeeApplicationTests.java')) {
        return contents['src/test/java/com/rxycode/t09coffee/CoffeeShopApplicationTest.java'] ?? ''
      }
      return contents[rel] ?? ''
    }),
    null
  )
  const nestedMaven = complete.filter((file) => file !== 'mvnw.cmd').concat([
    '.tools/apache-maven-3.9.16/apache-maven-3.9.16/bin/mvn.cmd'
  ])
  assert.equal(
    springMysqlArtifactIssue(nestedMaven, (rel) => contents[rel] ?? ''),
    null
  )
  const otherPackage = complete.map((file) => file.replace('com/rxycode/t09coffee/web/', 'com/rxycode/coffee/controller/'))
  assert.equal(
    springMysqlArtifactIssue(otherPackage, (rel) => {
      const key = rel.replace('com/rxycode/coffee/controller/', 'com/rxycode/t09coffee/web/')
      return contents[key] ?? contents[rel] ?? ''
    }),
    null
  )
  contents['src/main/java/com/rxycode/t09coffee/CoffeeShopApplication.java'] = 'package com.rxycode.t09coffee; @SpringBootApplication class CoffeeShopApplication {}'
  assert.equal(
    springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? ''),
    null
  )
  const orphanTest = 'src/test/java/com/rxycode/orphan/OrphanTest.java'
  contents[orphanTest] = 'package com.rxycode.orphan; @SpringBootTest @AutoConfigureMockMvc class OrphanTest { MockMvc mockMvc; void api() { mockMvc.perform(get("/api/health")); } }'
  assert.match(
    String(springMysqlArtifactIssue(complete.concat([orphanTest]), (rel) => contents[rel] ?? '')),
    /SpringBootConfiguration/
  )
  delete contents[orphanTest]
  contents['TEST-REPORT.md'] = '冒烟：待执行\n待填写'
  assert.match(
    String(springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? '')),
    /placeholders|Maven test counts/
  )
  contents['TEST-REPORT.md'] = '自动化测试 ⏳ 待验证\n测试用例数 若干'
  assert.match(
    String(springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? '')),
    /placeholders/
  )
  contents['TEST-REPORT.md'] = 'Tests run: 2, Failures: 0, Errors: 2, Time elapsed: 1.594 s <<< FAILURE!'
  assert.match(
    String(springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? '')),
    /Errors: 2/
  )
  contents['TEST-REPORT.md'] = 'mvn test\nTests run: 4, Failures: 0, Errors: 0\n4 passed'
  contents['src/test/java/com/rxycode/t09coffee/CoffeeShopApplicationTest.java'] = 'class CoffeeApplicationTest { @Test void mainClassShouldBeLoadable() { CoffeeApplication.class.getSimpleName(); } }'
  assert.match(
    String(springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? '')),
    /class-load|MockMvc/
  )
  contents['src/test/java/com/rxycode/t09coffee/CoffeeShopApplicationTest.java'] = '@SpringBootTest class CoffeeApplicationTest { @Test void contextLoads() {} }'
  assert.match(
    String(springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? '')),
    /contextLoads|MockMvc/
  )
  contents['src/test/java/com/rxycode/t09coffee/CoffeeShopApplicationTest.java'] = '@SpringBootTest @AutoConfigureMockMvc class CoffeeShopApplicationTest { MockMvc mockMvc; void api() { mockMvc.perform(get("/api/health")); } }'
  contents['pom.xml'] = '<project></project>'
  assert.match(
    String(springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? '')),
    /starter-flyway/
  )
  contents['pom.xml'] = '<project><dependencies><dependency><artifactId>spring-boot-starter-flyway</artifactId></dependency><dependency><artifactId>h2</artifactId></dependency></dependencies></project>'
  assert.match(
    String(springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? '')),
    /H2\/SQLite/
  )
  contents['pom.xml'] = '<project><dependencies><dependency><artifactId>spring-boot-starter-flyway</artifactId></dependency></dependencies></project>'
  const originalYml = contents['src/main/resources/application.yml']
  contents['src/main/resources/application.yml'] = `${originalYml}  jackson:\n    serialization:\n      write-dates-as-timestamps: false\n`
  assert.match(
    String(springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? '')),
    /write-dates-as-timestamps|Jackson 3/
  )
  contents['src/main/resources/application.yml'] = `${originalYml}# Do NOT set write-dates-as-timestamps here\n`
  assert.equal(
    springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? ''),
    null
  )
  contents['src/main/resources/application.yml'] = originalYml
  const goodTest = contents['src/test/java/com/rxycode/t09coffee/CoffeeShopApplicationTest.java']
  contents['src/test/java/com/rxycode/t09coffee/CoffeeShopApplicationTest.java'] = 'import com.fasterxml.jackson.databind.JsonNode; @SpringBootTest @AutoConfigureMockMvc class CoffeeShopApplicationTest { MockMvc mockMvc; void api() { mockMvc.perform(get("/api/health")); } }'
  assert.match(
    String(springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? '')),
    /fasterxml\.jackson\.databind|tools\.jackson/
  )
  contents['src/test/java/com/rxycode/t09coffee/CoffeeShopApplicationTest.java'] = 'import org.springframework.boot.test.autoconfigure.webmvc.AutoConfigureMockMvc; @SpringBootTest @AutoConfigureMockMvc class CoffeeShopApplicationTest { MockMvc mockMvc; void api() { mockMvc.perform(get("/api/health")); } }'
  assert.match(
    String(springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? '')),
    /autoconfigure\.webmvc/
  )
  contents['src/test/java/com/rxycode/t09coffee/CoffeeShopApplicationTest.java'] = 'import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc; @SpringBootTest @AutoConfigureMockMvc class CoffeeShopApplicationTest { MockMvc mockMvc; void api() { mockMvc.perform(get("/api/health")); } }'
  assert.match(
    String(springMysqlArtifactIssue(complete, (rel) => contents[rel] ?? '')),
    /autoconfigure\.web\.servlet/
  )
  contents['src/test/java/com/rxycode/t09coffee/CoffeeShopApplicationTest.java'] = goodTest
  assert.equal(mavenTestCountsIssue('Tests run: 2, Failures: 0, Errors: 0'), null)
  assert.match(String(mavenTestCountsIssue('Tests run: 2, Failures: 0, Errors: 2 <<< FAILURE!')), /Errors: 2/)
  contents['TEST-REPORT.md'] = 'mvn test\nTests run: 4, Failures: 0, Errors: 0\n4 passed'
  assert.equal(
    findProjectLocalMaven(['pom.xml', '.tools/apache-maven-3.9.16/bin/mvn.cmd', 'lib/mvn']),
    '.tools/apache-maven-3.9.16/bin/mvn.cmd'
  )
})

test('game play probe accepts Chinese running state and rejects the menu', () => {
  assert.equal(gameEnteredPlayableState('运行中', 0), true)
  assert.equal(gameEnteredPlayableState('菜单', 0), false)
  assert.equal(gameEnteredPlayableState('菜单', 12), true)
  assert.equal(gameEnteredPlayableState('running', 0), true)
  assert.equal(parseHudScore('得分 33'), 33)
})

test('painted canvas behind a visible start menu is not playable', () => {
  assert.equal(gameMenuStillBlockingPlay({ overlayHidden: false, startVisible: true, state: '', score: 0 }), true)
  assert.equal(gameMenuStillBlockingPlay({ overlayHidden: true, startVisible: false, state: '', score: 0 }), true)
  assert.equal(gameMenuStillBlockingPlay({ overlayHidden: false, startVisible: true, state: '', score: 22 }), false)
  assert.equal(gameMenuStillBlockingPlay({ overlayHidden: false, startVisible: false, state: '', score: 0 }), true)
  assert.equal(gameMenuStillBlockingPlay({ overlayHidden: true, startVisible: false, state: '运行中', score: 0 }), false)
})

test('dotenv parser keeps quoted values and skips comments', () => {
  const parsed = parseDotEnv('# comment\nMYSQL_USER=rxycode_t09\nMYSQL_PASSWORD="abc=def"\n\nSPRING_DATASOURCE_USERNAME=rxycode_t09\n')
  assert.equal(parsed.MYSQL_USER, 'rxycode_t09')
  assert.equal(parsed.MYSQL_PASSWORD, 'abc=def')
  assert.equal(parsed.SPRING_DATASOURCE_USERNAME, 'rxycode_t09')
  assert.equal(parsed['# comment'], undefined)
})

test('jdbc mysql url yields host port and database for the agent environment', () => {
  assert.deepEqual(
    mysqlPartsFromJdbc('jdbc:mysql://127.0.0.1:3306/rxycode_t09'),
    { MYSQL_HOST: '127.0.0.1', MYSQL_PORT: '3306', MYSQL_DATABASE: 'rxycode_t09' }
  )
  assert.deepEqual(mysqlPartsFromJdbc('not-a-jdbc-url'), {})
})

test('play probe reads the http url even when Electron leaves switches in argv', () => {
  assert.equal(
    playProbeUrl(['C:\\\\electron.exe', '--disable-gpu', 'play-probe.cjs', 'http://127.0.0.1:9/', 'shot.png']),
    'http://127.0.0.1:9/'
  )
})

test('static file server keeps /game.js inside the artifact root on Windows', () => {
  const root = 'D:\\\\artifact\\\\T01-runner'
  assert.equal(staticFilePath(root, '/game.js'), resolve(root, 'game.js'))
  assert.equal(staticFilePath(root, '/'), resolve(root, 'index.html'))
  assert.equal(staticFilePath(root, '/../secret.js'), null)
  assert.equal(
    webServeRoot('D:\\\\artifact\\\\T03-company', ['PLAN.md', 'public/index.html', 'public/login.html']),
    resolve('D:\\\\artifact\\\\T03-company', 'public')
  )
  assert.equal(
    webServeRoot('D:\\\\artifact\\\\T01-runner', ['index.html', 'game.js']),
    'D:\\\\artifact\\\\T01-runner'
  )
})

test('web play probe prefers explicit start buttons over the first button on the page', () => {
  const probe = readFileSync(new URL('./play-generated-page-probe.cjs', import.meta.url), 'utf8')
  assert.match(probe, /#btn-start|#startBtn/)
  const suite = readFileSync(new URL('./real-business-suite.mts', import.meta.url), 'utf8')
  assert.match(suite, /#btn-start, #startBtn/)
  assert.match(suite, /#start-btn/)
  assert.match(suite, /开始\|start\|play/)
  assert.match(suite, /canvasPainted|getImageData/)
  assert.match(suite, /data-action="newgame"/)
  assert.match(suite, /#screen-menu/)
  assert.match(suite, /#stat-score/)
  assert.match(suite, /startVisible/)
  assert.match(suite, /pageExceptions/)
  assert.match(suite, /admin\\\\.html/)
  assert.match(suite, /scenario\.timeoutMs/)
  assert.match(suite, /error === null && status !== 'succeeded'/)
  assert.match(suite, /desktopSuiteEnv|mysqlTestEnv/)
  assert.match(suite, /APP_ADMIN_PASSWORD|T09_ADMIN_PASSWORD/)
  assert.match(suite, /opencode-go\/mimo-v2\.5/)
  assert.match(suite, /opencode\.ai\/zen\/go\/v1/)
  assert.match(suite, /selectOpenCodeGoModelInSettings|assertOpenCodeGoModel/)
  assert.doesNotMatch(suite, /deepseek-v4-flash/)
  assert.doesNotMatch(suite, /api\.deepseek\.com/)
  const cliHarness = readFileSync(new URL('./real-business-cli-harness.mts', import.meta.url), 'utf8')
  assert.match(cliHarness, /opencode-go\/mimo-v2\.5/)
  assert.match(cliHarness, /opencode\.ai\/zen\/go\/v1/)
  assert.doesNotMatch(cliHarness, /deepseek-v4-flash/)
  assert.doesNotMatch(cliHarness, /api\.deepseek\.com/)
  assert.doesNotMatch(suite, /assertOfficialModel|selectOfficialModelInSettings/)
  assert.match(suite, /buildSpringMysqlRepairInstructions/)
  const authBeanRepair = buildSpringMysqlRepairInstructions("mvn test failed:\nNo qualifying bean of type 'org.springframework.security.authentication.AuthenticationManager'")
  assert.match(authBeanRepair, /ProviderManager\(daoAuthenticationProvider\)/)
  assert.doesNotMatch(authBeanRepair, /Do not rewrite the whole tree/)
  const duplicateSecurityRepair = buildSpringMysqlRepairInstructions('mvn test failed:\nCaused by: org.springframework.context.annotation.ConflictingBeanDefinitionException: Annotation-specified bean name \'securityConfig\'')
  assert.match(duplicateSecurityRepair, /single SecurityConfig/)
  assert.doesNotMatch(duplicateSecurityRepair, /Do not rewrite the whole tree/)
  const unauthorizedRepair = buildSpringMysqlRepairInstructions('mvn test failed:\nStatus expected:<200> but was:<401>')
  assert.match(unauthorizedRepair, /@WithMockUser is ignored/)
  assert.match(unauthorizedRepair, /\.with\(user\("admin"\)\.roles\("ADMIN"\)\)/)
  assert.doesNotMatch(unauthorizedRepair, /Do not rewrite the whole tree/)
  const login400Repair = buildSpringMysqlRepairInstructions('mvn test failed:\nStatus expected:<401> but was:<400>')
  assert.match(login400Repair, /@Valid/)
  assert.match(login400Repair, /401/)
  assert.doesNotMatch(login400Repair, /Do not rewrite the whole tree/)
  const backtickRepair = buildSpringMysqlRepairInstructions("mvn test failed:\n非法字符: '`'")
  assert.match(backtickRepair, /backtick|markdown fence/)
  assert.doesNotMatch(backtickRepair, /Do not rewrite the whole tree/)
  const sessionCastRepair = buildSpringMysqlRepairInstructions('mvn test failed:\n不兼容的类型: jakarta.servlet.http.HttpSession无法转换为org.springframework.mock.web.MockHttpSession')
  assert.match(sessionCastRepair, /Do not cast getSession/)
  assert.doesNotMatch(sessionCastRepair, /Do not rewrite the whole tree/)
  const lazyRepair = buildSpringMysqlRepairInstructions('mvn test failed:\norg.hibernate.LazyInitializationException: Cannot lazily initialize collection')
  assert.match(lazyRepair, /@Transactional|FetchType\.EAGER/)
  assert.doesNotMatch(lazyRepair, /Do not rewrite the whole tree/)
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'mvn test failed:\nHttpSession无法转换为org.springframework.mock.web.MockHttpSession',
      ['src/test/java/com/rxycode/t09coffee/CoffeeApiTest.java']
    ),
    ['src/test/java/com/rxycode/t09coffee/CoffeeApiTest.java']
  )
  const forbiddenRepair = buildSpringMysqlRepairInstructions('mvn test failed:\nStatus expected:<200> but was:<403>')
  assert.match(forbiddenRepair, /permitAll "\/api\/auth\/login"/)
  assert.match(forbiddenRepair, /APP_ADMIN_PASSWORD or T09_ADMIN_PASSWORD/)
  assert.doesNotMatch(forbiddenRepair, /Do not rewrite the whole tree/)
  const jacksonRefRepair = buildSpringMysqlRepairInstructions('mvn test failed:\n找不到符号\n  符号:   类 JsonBackReference')
  assert.match(jacksonRefRepair, /Delete @JsonManagedReference and @JsonBackReference/)
  assert.doesNotMatch(jacksonRefRepair, /put @JsonIgnore/)
  assert.doesNotMatch(jacksonRefRepair, /Do not rewrite the whole tree/)
  const jacksonAnnoRepair = buildSpringMysqlRepairInstructions('mvn test failed:\n[ERROR] 程序包tools.jackson.annotation不存在')
  assert.match(jacksonAnnoRepair, /tools\.jackson\.annotation does not exist/)
  assert.doesNotMatch(jacksonAnnoRepair, /Do not rewrite the whole tree/)
  const schemaRepair = buildSpringMysqlRepairInstructions('mvn test failed:\nCaused by: org.hibernate.tool.schema.spi.SchemaManagementException: Schema validation: missing table [inventory]')
  assert.match(schemaRepair, /CREATE TABLE users, products, inventory/)
  assert.match(schemaRepair, /ddl-auto/)
  assert.doesNotMatch(schemaRepair, /orElseThrow belongs on Optional/)
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'mvn test failed:\nCaused by: org.hibernate.tool.schema.spi.SchemaManagementException: Schema validation: missing table [inventory]',
      ['pom.xml', 'src/main/resources/db/migration/V1__init.sql', 'src/main/java/com/rxycode/t09/coffee/controller/AuthController.java']
    ),
    ['src/main/resources/db/migration/V1__init.sql']
  )
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'spring-mysql jpa.hibernate.ddl-auto=validate fails before Flyway creates tables; use none or update',
      ['src/main/resources/application.yml']
    ),
    ['src/main/resources/application.yml']
  )
  const missingServiceRepair = buildSpringMysqlRepairInstructions('mvn test failed:\n[ERROR]   符号:   类 RevenueService\n[ERROR]   位置: 类 com.rxycode.t09coffee.controller.RevenueController')
  assert.match(missingServiceRepair, /under src\/main\/java\/\.\.\.\/service/)
  assert.match(missingServiceRepair, /Do not only add imports/)
  assert.doesNotMatch(missingServiceRepair, /Do not rewrite the whole tree/)
  assert.deepEqual(
    selectMissingFileRepair(
      'T09',
      'mvn test failed:\n[ERROR] ProductController.java:[14,19] 找不到符号\n[ERROR]   符号:   类 RevenueService\n[ERROR]   符号:   类 RevenueDto',
      [
        'src/main/java/com/rxycode/t09coffee/controller/ProductController.java',
        'src/main/java/com/rxycode/t09coffee/controller/RevenueController.java',
        'src/main/java/com/rxycode/t09coffee/dto/ProductDto.java'
      ]
    ).sort(),
    [
      'src/main/java/com/rxycode/t09coffee/dto/RevenueDto.java',
      'src/main/java/com/rxycode/t09coffee/service/ProductService.java',
      'src/main/java/com/rxycode/t09coffee/service/RevenueService.java'
    ].sort()
  )
  const serviceWrite = buildMissingFileRepairPrompt('T09-coffee', ['src/main/java/com/rxycode/t09coffee/service/RevenueService.java'])
  assert.match(serviceWrite, /compilable class/)
  assert.match(serviceWrite, /RevenueService\.java/)
  const orderStatusRepair = buildSpringMysqlRepairInstructions('mvn test failed:\nNo value at JSON path "$.status"')
  assert.match(orderStatusRepair, /jsonPath\("\$\.id"\)/)
  assert.doesNotMatch(orderStatusRepair, /Do not rewrite the whole tree/)
  assert.doesNotMatch(suite, /t09coffee\/web\/AuthController/)
  assert.match(suite, /MYSQL_PASSWORD/)
  assert.match(suite, /artifactKind === 'spring-mysql' \? 8/)
  assert.match(suite, /You must call bash to run project-local mvn/)
  assert.match(suite, /runProjectLocalMvnTest|harness mvn test observed/)
  assert.match(suite, /hasJava \? runProjectLocalMvnTest/)
  assert.match(suite, /Caused by:/)
  assert.match(suite, /cannot start with ROLE_/)
  assert.match(suite, /Status expected:</)
  assert.match(suite, /csrf403|was:<403>/)
  assert.match(suite, /class-load\|MockMvc/)
  assert.match(suite, /DROP TABLE IF EXISTS|FOREIGN_KEY_CHECKS/)
  assert.match(suite, /GROUP_CONCAT|PREPARE stmt/)
  assert.match(suite, /leftover tables/)
  assert.match(suite, /DROP VIEW IF EXISTS/)
  assert.match(suite, /surefireText|surefire-reports/)
  assert.match(suite, /SpringBootConfiguration/)
  assert.match(suite, /decodeXmlEntities|Unable to find a @SpringBootConfiguration/)
  assert.match(suite, /jdbc:h2/)
  assert.match(suite, /write-dates-as-timestamps|Jackson 3/)
  assert.match(suite, /fasterxml\\.jackson\\.databind|autoconfigure\\.webmvc/)
  assert.match(suite, /Flyway SQL\|ddl-auto=validate\|created menus/)
  assert.match(suite, /executeQuery/)
  assert.match(suite, /mysql schema reset failed/)
  assert.match(suite, /Migration checksum mismatch/)
  assert.match(suite, /Downloading Maven|找不到指定的路径/)
  assert.match(suite, /resetMysqlTestSchema|DROP DATABASE IF EXISTS/)
  assert.match(suite, /mavenTestCountsIssue/)
  assert.match(suite, /BUILD FAILURE/)
  assert.match(suite, /file\.encoding=UTF-8/)
  const scenarios = readFileSync(new URL('./real-business-scenarios.mts', import.meta.url), 'utf8')
  assert.match(scenarios, /@RestController/)
  assert.match(scenarios, /do not rename or relocate/)
  assert.match(scenarios, /Tests run: N/)
  assert.match(scenarios, /DATETIME NOT NULL|updatedAt/)
  assert.match(scenarios, /SpringBootConfiguration/)
  assert.match(scenarios, /WRITE_DATES_AS_TIMESTAMPS|write-dates-as-timestamps/)
  assert.match(scenarios, /tools\.jackson\.databind/)
  assert.match(scenarios, /ProviderManager\(daoAuthenticationProvider\)/)
  assert.match(scenarios, /config\.SecurityConfig and security\.SecurityConfig/)
  assert.match(scenarios, /Do not use @WithMockUser/)
  assert.match(scenarios, /Do not add com\.h2database/)
  assert.match(scenarios, /org\.h2\.Driver/)
  assert.match(scenarios, /permitAll "\/api\/auth\/login"/)
  assert.match(scenarios, /not a hardcoded password/)
  assert.match(scenarios, /JsonManagedReference, @JsonBackReference/)
  assert.match(scenarios, /CREATE TABLE users, products, inventory/)
  assert.match(scenarios, /menus\/customers in place of products/)
  assert.match(scenarios, /ddl-auto to none or update/)
  assert.match(scenarios, /must not Integer\.parseInt/)
  assert.match(suite, /output directory was not created/)
  assert.match(suite, /missingOutputDirIssue/)
  assert.match(suite, /artifactKind === 'spring-mysql'\) return \[\]/)
  assert.match(scenarios, /T09_coffee/)
  assert.match(suite, /not a parkour\/platformer game/)
  assert.match(suite, /a\[href\^="#"\]/)
  assert.match(suite, /companyPagePlayExpression|#btn-open-login/)
  assert.match(suite, /a\.btn-login|#loginUsername/)
  assert.match(suite, /#authForm/)
  assert.match(suite, /scenariosFrom/)
  assert.match(suite, /webServeRoot/)
  assert.match(suite, /travelWebsiteArtifactIssue/)
  assert.match(suite, /marketBiArtifactIssue/)
  assert.match(suite, /evTcoArtifactIssue/)
  assert.match(suite, /rentalDecisionArtifactIssue/)
  assert.match(suite, /For T06, call the write tool immediately/)
  assert.match(suite, /For T07, call the write tool immediately/)
  assert.match(suite, /For T08, call the write tool immediately/)
  assert.match(suite, /Do not load Chart\.js or any CDN/)
  assert.match(suite, /Do not call bash, python, node, Java, Spring/)
  assert.match(suite, /host-resolver-rules/)
  assert.match(suite, /setLifecycleEventsEnabled/)
  assert.match(suite, /Do not write _probe\.py/)
  assert.match(suite, /firstTokenHardFail/)
  assert.match(suite, /__rxyWatchdog/)
  assert.match(suite, /lastVisibleAt/)
  assert.match(suite, /inFlightTools/)
  assert.match(suite, /IN_FLIGHT_TOOL_STALL_MS/)
  assert.match(suite, /idle > \$\{IN_FLIGHT_TOOL_STALL_MS\}/)
  assert.match(suite, /pendingToolPrep/)
  assert.match(suite, /preparing write tool call/)
  assert.match(suite, /runAbortedByWatchdog && attempt > 1/)
  assert.doesNotMatch(suite, /tool-activity\.running/)
  assert.match(suite, /sawActive/)
  assert.match(suite, /PROTOCOL_CAPTURE_BOOTSTRAP/)
  assert.match(suite, /never left the queue/)
  assert.match(suite, /runAbortedByWatchdog/)
  assert.match(suite, /hasInFlightRecovery/)
  assert.match(suite, /three-file index.html\/README.md\/TEST-REPORT.md stub/)
  assert.match(suite, /failedStateStartedAt/)
  assert.match(suite, /selectJavaSwingMain/)
  assert.match(suite, /-d', classOut/)
  assert.match(suite, /javac -encoding UTF-8 -d a classes directory/)
  assert.match(suite, /hop < 5/)
  assert.match(suite, /department\/employee CRUD/)
  assert.match(suite, /selectMissingFileRepair/)
  assert.match(suite, /no-websearch rule does not forbid write/)
  assert.match(suite, /if \(scenario\.id === 'T03'\) return \[\]/)
  assert.match(suite, /T03'\) return \['index.html', 'admin.html'/)
  assert.match(suite, /navigated or closed/)
  assert.match(suite, /headless=new/)
  assert.match(suite, /Chrome may keep the profile directory locked/)
})

test('a follow-up prompt stops a still-running task before typing into the composer', () => {
  const suite = readFileSync(new URL('./real-business-suite.mts', import.meta.url), 'utf8')
  assert.match(suite, /async function stopActiveTask/)
  assert.match(suite, /if \(await harness\.has\('\[data-testid="composer-stop"\]'\)\)/)
  assert.match(suite, /composer-stop/)
  assert.match(suite, /beforeToolCount/)
  assert.match(suite, /let sawActive = false/)
  assert.doesNotMatch(suite, /stopVisible \|\| recovering/)
  assert.doesNotMatch(suite, /tool-activity\.running/)
})

test('one-shot approval storms and long wall clocks are hard failures', () => {
  assert.equal(approvalStormIssue(12), null)
  assert.match(String(approvalStormIssue(13)), /approval storm/)
  assert.equal(taskWallClockIssue(45 * 60 * 1000), null)
  assert.match(String(taskWallClockIssue(45 * 60 * 1000 + 1)), /45m hard-fail/)
  const suite = readFileSync(new URL('./real-business-suite.mts', import.meta.url), 'utf8')
  assert.match(suite, /always-allow/)
  assert.match(suite, /save-rule/)
  assert.match(suite, /input\[value="any"\]/)
  assert.doesNotMatch(suite, /composer-stop"\]'\)\) return 0/)
})

test('synthetic waiting progress does not reset the real-work watchdog', () => {
  assert.equal(isMeaningfulProtocolEvent({ method: 'event/progress', params: { text: '正在等待模型响应…' } }), false)
  assert.equal(isMeaningfulProtocolEvent({ method: 'event/progress', params: { text: 'Build in progress... 30s' } }), false)
  assert.equal(isMeaningfulProtocolEvent({ method: 'event/progress', params: { text: 'Thinking... (round 1)' } }), true)
  assert.equal(isMeaningfulProtocolEvent({ method: 'event/message_delta', params: { text: 'token' } }), true)
})

test('an in-flight tool is not treated as GUI silence', () => {
  const begin = { method: 'event/tool_begin', params: { session_id: 's1', call_id: 'c1' }, __at_ms: 1000 }
  const waiting = { method: 'event/progress', params: { session_id: 's1', text: '正在等待模型响应…' }, __at_ms: 20000 }
  const ended = { method: 'event/tool_end', params: { session_id: 's1', call_id: 'c1' }, __at_ms: 62000 }
  assert.equal(hasInFlightTool([begin, waiting], 's1', 1000), true)
  assert.equal(hasInFlightTool([begin, waiting, ended], 's1', 1000, 62000), true)
  assert.equal(hasInFlightTool([begin, waiting, ended], 's1', 62000), false)
})

test('Swing smoke launches the JFrame main rather than a *Test driver', () => {
  assert.equal(
    selectJavaSwingMain([
      {
        path: 'test/NumberBombTest.java',
        source: 'package com.rxy.bomb;\npublic class NumberBombTest { public static void main(String[] args) { System.exit(1); } }'
      },
      {
        path: 'test/GuiAcceptanceDriver.java',
        source: 'package com.rxy.bomb;\nimport javax.swing.*;\npublic class GuiAcceptanceDriver { public static void main(String[] args) { } }'
      },
      {
        path: 'src/main/java/com/rxy/bomb/NumberBombGUI.java',
        source: 'package com.rxy.bomb;\nimport javax.swing.JFrame;\npublic class NumberBombGUI { public static void main(String[] args) { new JFrame().setVisible(true); } }'
      }
    ]),
    'com.rxy.bomb.NumberBombGUI'
  )
})

test('an in-flight recovery is not treated as GUI silence', () => {
  const started = { method: 'event/recovery_started', params: { session_id: 's1' }, __at_ms: 1000 }
  const attempt = { method: 'event/recovery_attempt', params: { session_id: 's1' }, __at_ms: 2000 }
  const waiting = { method: 'event/progress', params: { session_id: 's1', text: '正在等待模型响应…' }, __at_ms: 20000 }
  const exhausted = { method: 'event/recovery_exhausted', params: { session_id: 's1' }, __at_ms: 40000 }
  assert.equal(hasInFlightRecovery([started, attempt, waiting], 's1', 2000), true)
  assert.equal(hasInFlightRecovery([started, attempt, waiting, exhausted], 's1', 2000, 40000), true)
  assert.equal(hasInFlightRecovery([started, attempt, waiting, exhausted], 's1', 40000), false)
})

test('layout evaluator catches overlap, clipping and composer coverage', () => {
  const result = evaluateLayoutSnapshot({
    viewport: { width: 800, height: 700 },
    horizontalScroll: 0,
    elements: [
      { id: 'timeline', left: 80, top: 80, right: 780, bottom: 620 },
      { id: 'composer', left: 80, top: 560, right: 780, bottom: 720 },
      { id: 'button', left: 760, top: 20, right: 820, bottom: 50 }
    ]
  })
  assert.ok(result.issues.some((issue) => issue.kind === 'overlap'))
  assert.ok(result.issues.some((issue) => issue.kind === 'clipped'))
  assert.ok(result.issues.some((issue) => issue.kind === 'composer_coverage'))
})

test('layout evaluator tolerates subpixel sibling boundaries but catches real overlap', () => {
  assert.deepEqual(evaluateLayoutSnapshot({
    viewport: { width: 100, height: 100 },
    horizontalScroll: 0,
    elements: [
      { id: 'chat', left: 0, top: 0, right: 100, bottom: 60.0001 },
      { id: 'composer', left: 0, top: 60.0002, right: 100, bottom: 100.0001 }
    ]
  }).issues, [])
  assert.ok(evaluateLayoutSnapshot({
    viewport: { width: 100, height: 100 },
    horizontalScroll: 0,
    elements: [
      { id: 'chat', left: 0, top: 0, right: 100, bottom: 61 },
      { id: 'composer', left: 0, top: 60, right: 100, bottom: 100 }
    ]
  }).issues.some((issue) => issue.kind === 'overlap'))
})

test('timeline checker requires chronological tool results and final answer', () => {
  assert.deepEqual(
    timelineKinds([
      { kind: 'prompt' },
      { kind: 'assistant' },
      { kind: 'tool' },
      { kind: 'tool_result' },
      { kind: 'recovery' },
      { kind: 'tool' },
      { kind: 'tool_result' },
      { kind: 'final' }
    ]),
    { valid: true, issue: null }
  )
  assert.equal(
    timelineKinds([{ kind: 'tool_result' }, { kind: 'tool' }, { kind: 'final' }]).valid,
    false
  )
})
