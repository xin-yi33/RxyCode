你是 GX 前端审计员。只审 GX28-H。不要以看不到仓库判 FAIL。未改 schema/appserver。Desktop only，不改 opentui-app。
team/list|groups|install|set_active 存在，路径 A。
已实现 TeamPicker（分组→团队→详情+成本提示）、TeamInstallPanel（确认+选分组）、TeamSection（Auto + token 弹窗）、TeamManager 五态。
SETTINGS_SECTIONS.team 已解锁（不再 blocked）。测试 import 这些组件，缺失会失败。
第一行必须逐字：VERDICT: PASS 或 VERDICT: FAIL。
