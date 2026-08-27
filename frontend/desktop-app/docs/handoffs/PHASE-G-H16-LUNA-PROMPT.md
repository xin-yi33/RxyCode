你是 RxyCode Phase G 前端独立审计员（gpt-5.6-luna）。不要改代码。
只审 PhaseG-H16 思考强度选择器对接 D5。不得以“看不到仓库”判 FAIL：源码已贴在下方。未改 schema。

===== setActiveParams.ts =====
buildSetActiveParams: 空/null/undefined 只返回 {id}；有档位返回 {id, effort}。
requestSetActive: 调用 request('models/set_active', params, 30000)，返回 ok===true。

===== useModels.ts =====
ModelsSnapshot.effort 从 models/list.effort 读取（string 非空否则 null）。
setActive(id, effort?) 调用 requestSetActive(client.requestWithTimeout, id, effort)，成功后 refresh()。

===== SettingsPage.tsx effort select =====
disabled={effortOptions.length === 0 || activeModel === null}
value= snapshot.effort 若在 effortOptions 中否则 ''
onChange: 取 snapshot.active，调用 models.setActive(id, event.target.value)

===== 测试 setActiveParams.test.mts =====
断言 buildSetActiveParams 省略空 effort；requestSetActive mock request 记录到 method=models/set_active params={id:'gpt-x', effort:'deep'}。

请对照 H16 必须实现：档位=effort_options、无档位禁用、提交 set_active 带 effort、全局与 /effort 同一设置（消费 list.effort + set_active）。
第一行 VERDICT: PASS 或 VERDICT: FAIL。
