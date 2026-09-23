VERDICT: PASS

§7 P3「macOS/Linux 构建目标 smoke（locale 入包 + 启动握手）」满足：

- `electron-builder.yml` 已声明 macOS `dmg`、Linux `AppImage` 与 `deb` 构建目标。
- `extraResources` 将 `src/i18n/locales` 打入 `locales`，满足 locale 入包要求。
- `t.ts` 显式导入 `zh-CN.json` 与 `en.json`，renderer bundle 具备 locale 内容。
- `platform/index.mts` 启动握手仍通过 `ProtocolClient + initializeHandshake`，路径未被改写。
- `linuxStartup.shouldDisableLinuxSandbox` 仅作用于 packaged Linux，范围符合预期。
- `tests/h13-packaging-targets.test.mts` 3 项通过，已覆盖相关配置与路径检查。
- `protocol/schema.json` 未改动。

本机无法实跑 macOS/Linux 安装器，且无跨 OS runner，记为 `BLOCKED_RUNTIME`；不据此判 FAIL，也不要求 mock 假产物或修改 Python/schema。