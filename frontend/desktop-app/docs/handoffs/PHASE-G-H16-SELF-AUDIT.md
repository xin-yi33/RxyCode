# PhaseG-H16 自审

左下角入口：SessionList 底部 `.settings-entry` 圆角 6px，图标+“设置”，data-testid=open-settings，hover 同 H15。
8 分区：SETTINGS_SECTIONS 导航 + 懒加载当前分区。
模型选择/添加：models + addModel 复用 D5，零后端改动；effort 无档位禁用。
团队/回收站/技能/MCP：BLOCKED_PREREQUISITE，不 mock。
对齐 H10 三层折叠：TEAM_SECTION_ALIGN 声明仍在。
typecheck:web 通过。
