你是 RxyCode Phase G 前端独立审计员（gpt-5.6-luna）。不要改代码。
只审 PhaseG-H14 剩余判据：全部静态文案迁移完成（GX22 文案清单配合）。
分支 feat/phase-g-frontend。不得因尚未 commit 判 FAIL。

对照 PHASE-G-FRONTEND.md PhaseG-H14：
- locales/{zh-CN,en}.json 为词表真相，t(key, vars) 取词
- 全部 UI 静态文案经 t()；动态内容（会话文本/工具输出/模型回复）不入 i18n
- 切换语言不影响对话回复语言
- 系统语言首次进入 + 设置切换持久化
- Renderer 不直连 Python/HTTP；不改 protocol/schema.json

本卡 diff 要点：
- JSON 词表扩到 100+ key，中英 key 对齐
- t.ts 从 JSON import
- I18nProvider 挂 App；首次无 localStorage 时用 appserver get-info.systemLocale = app.getLocale()
- App/SessionList/SettingsPage/Composer/PlusMenu/GoalDialog/TaskHeader/ApprovalModal/ApprovalRulesModal/QuestionModal 静态 chrome 改 t()
- 测试：t.test.mts 证明 key 对齐且 isChatTextLocalized 原样返回
- typecheck 通过
- npm test 327 pass / 2 fail：H1 contextIsolation 正则仍找 index.ts 字面量（实际在 web-preferences.ts，H3 已落地）以及 geometry CSS 正则。均非本卡引入。

自审：PHASE-G-H14-SELF-AUDIT.md

第一行必须是：
VERDICT: PASS
或
VERDICT: FAIL
FAIL 只列 H14 规范内必改项。不要发挥 H15/H16。
