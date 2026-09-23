VERDICT: PASS

- **Electron 三端 OS 通知**：`electronOsNotify` 在 `Notification` 为函数时执行 `new Notification(title, { body })`，满足 toast 调用要求。
- **通知不可用/异常降级**：
  - `Notification` 不存在时返回 `false`；
  - 构造通知抛错时捕获并返回 `false`；
  - `dispatchRunEndNotice` 对 `false` 或异常统一调用 `showBanner`，返回 `'banner'`。
- **真实运行结束触发**：`watchRunStateTransitions` 仅在 `running → cancelled/failed/timed_out` 时触发，状态条件符合 PhaseG-H17。
- **App 接线**：`App.tsx` 的 `useEffect` 监听 `runStateBySession`，调用 `dispatchRunEndNotice`，OS 通知使用 `electronOsNotify`，降级横幅使用 `setRunBanner`。
- **应用内横幅**：存在 `data-testid="os-fallback-banner"`，具备可验证的 Linux 降级 UI。
- **测试覆盖**：`notify.test.mts` 使用 `MockNotification` 记录构造调用，并覆盖 `osNotify` 抛异常后走 banner 的路径；已对通知层进行 mock，并驱动 `electronOsNotify` / `dispatchRunEndNotice` 的关键行为。

未发现需要修改 schema 或其他超出 PhaseG-H17 范围的问题。