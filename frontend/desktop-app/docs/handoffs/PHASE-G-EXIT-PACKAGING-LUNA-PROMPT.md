你是 RxyCode Phase G 前端独立审计员（gpt-5.6-luna）。不要改代码。
只审 §7 P3：「macOS/Linux 构建目标 smoke（locale 入包 + 启动握手）通过」。
不得因尚未 commit 或看不到仓库判 FAIL。本机是 Windows，不能实跑 dmg/AppImage 安装器；不要因此要求改 Python/schema。

证据：
- electron-builder.yml：win nsis、mac dmg、linux AppImage + deb
- extraResources：src/i18n/locales → locales（locale 入包）
- t.ts import zh-CN.json / en.json（进 renderer bundle）
- platform/index.mts 启动握手仍走 ProtocolClient + initializeHandshake
- linuxStartup.shouldDisableLinuxSandbox 仅 packaged Linux
- tests/h13-packaging-targets.test.mts 3 通过
- 未改 protocol/schema.json
- 跨 OS 实机启动：BLOCKED_RUNTIME（无 macOS/Linux runner），不 mock 假产物

若配置+locale 入包+握手路径测试已满足「构建目标 smoke」，判 PASS。
若你认为必须实跑 dmg/AppImage 才算过，判 FAIL 并只写这一条。

第一行 VERDICT: PASS 或 FAIL。
