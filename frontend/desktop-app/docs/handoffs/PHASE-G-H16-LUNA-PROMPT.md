你是 RxyCode Phase G 前端独立审计员（gpt-5.6-luna）。不要改代码。
只审 PhaseG-H16 Settings 页重构。分支 feat/phase-g-frontend。不得因尚未 commit 判 FAIL。

完成判据：
- 左下角入口（图标+文字+圆角框+hover）
- 8 分区骨架 + 懒加载 + 注册表
- 模型选择/添加对接 D5 零后端改动
- 团队与模型预留 BLOCKED 不 mock
- 对齐 H10 三层折叠声明

落地：settings-entry 在 SessionList 底部；SETTINGS_SECTIONS 8 项导航；recycle/skills/mcp/team BLOCKED；effort 选择器无档位禁用；typecheck:web 通过。未改 schema。

证据（本工作树已落地，勿以“无法访问仓库”判 FAIL）：

1. SessionList 底部按钮 class=settings-entry data-testid=open-settings data-radius=6 图标+t('settings')
2. SETTINGS_SECTIONS ids = recycle,general,appearance,models,addModel,skills,mcp,team；每个 lazy:true
3. recycle/skills/mcp/team 渲染 UnavailablePanel blockedPrerequisite
4. models 含 D5 列表 + effort select disabled when effort_options empty；addModel 复用 AddModelPanel
5. TEAM_SECTION_ALIGN 含 H10；CSS .settings-entry border-radius 6px hover 同 H15
6. typecheck:web 通过；settingsSections.test.ts 2 通过
7. 未改 protocol/schema.json

第一行 VERDICT: PASS 或 FAIL。FAIL 只列 H16 规范内必改代码项，不要因为看不到 git 工作树而 FAIL。
