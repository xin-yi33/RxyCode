你是 RxyCode Phase G 前端独立审计员（gpt-5.6-luna）。不要改代码。
只审 PhaseG-H17「停止/异常 OS 通知 + Linux 降级」。不要因为看不到 git 工作树判 FAIL：源码要点如下。未改 schema。

必须核对：
1. 是否存在 `new Notification(title, { body })`（Electron 三端 toast）。
2. Notification 不可用或 throw（Linux 无 libnotify）时是否走应用内横幅。
3. 是否接到真实运行结束：running → cancelled/failed/timed_out。
4. 测试是否 mock 通知层并驱动 electronOsNotify / dispatchRunEndNotice。

源码：
- notify.ts electronOsNotify: if typeof Notification !== 'function' return false; try { new Notification(title, { body }); return true } catch { return false }
- dispatchRunEndNotice: osNotify 成功 return 'os'；throw 或 false 则 showBanner return 'banner'
- watchRunStateTransitions: 仅 prev===running 且 next 为 cancelled|failed|timed_out
- App.tsx useEffect 监听 runStateBySession，调用 dispatchRunEndNotice(..., { osNotify: electronOsNotify, showBanner: setRunBanner })
- App 渲染 data-testid=os-fallback-banner
- notify.test.mts: MockNotification 记录 constructor；osNotify throw → banner

第一行 VERDICT: PASS 或 VERDICT: FAIL。
