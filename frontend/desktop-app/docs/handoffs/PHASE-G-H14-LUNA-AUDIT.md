VERDICT: PASS

PhaseG-H14 审核结论：通过。

- `locales/{zh-CN,en}.json` 已作为词表真相，且中英文 key 对齐；词表已扩展至 100+ key。
- `t.ts` 已从 JSON 词表导入，静态文案通过 `t(key, vars)` 获取。
- `App`、`SessionList`、`SettingsPage`、`Composer`、`PlusMenu`、`GoalDialog`、`TaskHeader`、`ApprovalModal`、`ApprovalRulesModal`、`QuestionModal` 的静态 UI 文案已迁移。
- 动态会话文本、工具输出、模型回复未纳入 i18n，符合动态内容边界。
- `I18nProvider` 已挂载于 `App`。
- 首次无 `localStorage` 时使用 appserver `get-info.systemLocale`，其值来自 `app.getLocale()`。
- 设置切换具备持久化；语言切换不改变对话回复语言。
- Renderer 未新增直连 Python/HTTP 的行为。
- 未修改 `protocol/schema.json`。
- `t.test.mts` 已覆盖 key 对齐及 `isChatTextLocalized` 原样返回行为。
- Typecheck 通过。
- npm test 中剩余的 2 个失败项分别属于既有 H1 contextIsolation 正则误报及 H3 geometry CSS 正则问题，均非本卡 H14 引入，不影响 H14 判定。
- 未因尚未 commit 判定失败。