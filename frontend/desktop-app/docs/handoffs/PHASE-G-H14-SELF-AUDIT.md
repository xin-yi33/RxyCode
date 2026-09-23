# PhaseG-H14 自审

卡：i18n 语言本地化基建（剩余判据：全部静态文案迁移）
分支：feat/phase-g-frontend
协议变化：none

## 完成判据对照

1. locales/{zh-CN,en}.json + t()：JSON 为唯一词表，t.ts `with { type: 'json' }` 导入；I18nProvider 挂在 App。
2. 系统语言：appserver:get-info 已透传 app.getLocale() → systemLocale；首次无 localStorage 时按系统语言生效并持久化。
3. 设置切换 + 持久化：Settings 语言选项走 t()，desktopPreferences.v1 保存 language。
4. 对话回复语言不受影响：isChatTextLocalized 原样返回；timeline/user/model 文本不经 t()。
5. 全部静态文案：App/SessionList/SettingsPage/Composer/PlusMenu/GoalDialog/TaskHeader/ApprovalModal/ApprovalRulesModal/QuestionModal 静态 chrome 经 t()。动态内容（会话标题、workspace 路径、model id、option.label、toolName、消息正文）不入 i18n。

## 验收

- npm run typecheck：通过
- src/i18n/t.test.mts：3 通过（中英 key 对齐、聊天原文不变）

## DC

- DC-J1 未引入 Python/HTTP
- DC-J2 未复制后端状态机
- 未改 protocol/schema.json、appserver、core

## 已知限制

- ChatArea/TaskInspector 部分 inspector 英文标签仍有残留，下一轮 H15/H17 接线时继续收口
- AddModelPanel 探测过程 notice 仍有少量中文操作反馈
