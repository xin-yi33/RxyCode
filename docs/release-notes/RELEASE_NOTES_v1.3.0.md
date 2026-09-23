# RxyCode v1.3.0

RxyCode 是一个规划执行型的 AI 编程助手：把复杂任务自动拆解成子任务，通过安全工具编排器执行、验证结果后综合出最终答案，全程实时流式输出到终端或桌面界面。
> **推荐使用 v1.3.0。** 这一版是 Desktop GUI 的主版本：`rxycode gui` 打开的不再是 1.2.10 那扇“能聊天的窗口”，而是和 OpenTUI 共用同一套无头 `Session` 的工作台——项目 / 最近 / 置顶、运行中任务条、权限三档、插件主栏、侧边对话、计划 / 目标。默认 CLI 不变：在 cmd（或任意终端）里输入 `rxycode` 就是 OpenTUI。协议版本仍为 `1.1.0`。本页 **不对 macOS 打包**。

## 简要说明 / Summary

1.2.11 / 1.2.12 只发 CLI 的 `tar.gz`，Desktop 还停在 v1.2.10。**v1.3.0 把 GUI 重新放回主发布线**，并且把 1.2.10 之后积下来的工作台一次性交出去。

- 新增：Desktop 三栏工作台（会话分类、运行态 chrome、sash 吸附、Files / Browser 顶栏）
- 新增：权限三档、插件主栏（GitHub / Canva OAuth）、侧边对话、计划 / 目标（沿用并接到新壳）
- 新增：Windows `setup.exe`（可选安装目录、预览、桌面快捷方式）+ 便携 zip；Linux AppImage
- 修复：Windows 上新建会话发 `hi` 卡在 Starting Agent worker / 600s prompt timeout（worker bootstrap 与 stdin 死锁）
- 变更：产品版本 **1.3.0**；GitHub Release 同时发布 CLI sdist 与 Desktop 安装包；**无 macOS 资源**

## 亮点 / Highlights

- **GUI 是这次的主菜** —— 1.2.10 证明 Electron 能起来；1.3.0 把会话、项目、权限、插件、审批、计划做成日常能用的工作台
- **同一颗大脑** —— Desktop 和 OpenTUI 都走 `python -m appserver` → `Session` → `AgentV2`，不是两套 Agent
- **Windows 安装器和上次一样** —— 默认 `%USERPROFILE%\.rxycode\desktop`，可 Browse 改路径，桌面快捷方式默认勾选可取消，安装器语言跟系统
- **Linux 有 AppImage** —— `chmod +x` 后运行；缺 FUSE 时 `APPIMAGE_EXTRACT_AND_RUN=1`
- **CLI 没换入口** —— `rxycode` 仍是 OpenTUI；CLI 包里没有 Electron
- **首字与前缀缓存门仍在仓库里** —— 简单回复 1s、复杂首字 3s、Primary 前缀缓存 97% 是 Phase L/M 写下的硬门槛，不随 GUI 换壳而放宽

## 详细说明 / Details

### 新增功能

- **会话侧栏** —— 置顶 / 项目 / 最近；最近旁 `+` 新建任务；草稿任务；标题过长悬停滚动；运行中转圈在任务名前面，灰条拉满整行（`frontend/desktop-app/src/renderer/src/components/SessionList.tsx`）
- **项目夹** —— 悬停才出现 `…` 和 `+`；右键菜单；新建项目对话框（`features/projects/`）
- **三栏 sash** —— 中栏 / 右栏可拖，靠近边缘吸附（`features/shell/snapSash.ts`）
- **Files / Browser** —— 从右侧常驻栏收成顶栏图标，避免空黑块占位（`features/shell/WorkbenchToggles.ts`）
- **Composer 权限菜单** —— 更改前询问 / 自动编辑 / 完全访问；完全访问二次确认
- **插件主栏** —— 插件不再挤在设置里：GitHub / Canva 走 `plugin/connect/start`，token 只进 `user.json`
- **computer-use 适配器插件** —— 与 catalog 同一套安装/列表契约，不含截图式 GUI-agent 内核
- **侧边对话** —— 只读派生会话，可关（`features/sidechat/`）
- **计划 / 目标 / `+` 菜单** —— 1.2.10 已有能力接到新壳：计划卡片「是，实施此计划 / 补充说明 / 跳过」；Goal 对话框 Esc / 点遮罩关闭
- **模块清单与开发顺序** —— `docs/modules/catalog.yaml`、`docs/DEVELOPMENT-ORDER.md`
- **打包矩阵** —— Windows NSIS + zip、Linux AppImage（`electron-builder.yml`、`.github/workflows/release.yml`）

### 修复的 Bug

- **Starting Agent worker 直到 600s** —— worker 在 Windows 上把 bootstrap 的 `import langchain_openai` 和 piped `stdin.readline` 叠在一起会死锁。现在只有 `prompt` / `interrupt` 与 readline 并行，bootstrap 等 RPC 必须 await（`appserver/agent_worker.py`）
- **GLM / OpenCode Go 400** —— 去掉网关不接受的 extra（`core/providers/glm.py`）
- **本地「当前工作目录」任务误走 websearch** —— 不再因搜索失败整轮中断
- **只读任务被空 evidence 覆盖** —— 回答不再被失败的只读探测替换
- **评测串台** —— AgentV2 评测工厂调用 `set_session`，避免 MemoryManager `latest` 串到下一题
- **OAuth token 交换** —— POST 使用授权 URL 里的同一个 `client_id`

### 变更

- 产品版本 **1.3.0**：`pyproject.toml`、`install.ps1` / `install.sh`、OpenTUI / Ink 头部、MCP `clientInfo`、`protocol.version.APPSERVER_VERSION`、`packaging/runtimes/*.json`、Desktop `package.json`。协议版本保持 `1.1.0`（`protocol/schema.json` 冻结字段未改）
- GitHub Release 从「只发 sdist」改回 **sdist + Desktop**。**没有** macOS `.dmg` / `arm64-mac.zip`
- Desktop 设置「关于」显示 **1.3.0**（打包应用读 `app.getVersion()`）
- 模块 catalog 不再列出未跟踪的 `game/` 演示

## 安装 / Install

**CLI / OpenTUI（不含 Electron）：** 下面三步只装终端。装完输入 `rxycode`。**不要**指望这时 `rxycode gui` 能打开——CLI 包里没有桌面程序。

```powershell
# Windows
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.3.0/install.ps1 | iex"
rxycode
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.3.0/install.sh | sh
rxycode
```

```bash
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.3.0"
rxycode
```

From this release asset:

```bash
python -m pip install rxycode-1.3.0.tar.gz
rxycode
```

**桌面 GUI（需另下本页 Desktop 资产）：**

| 系统 | 怎么开 |
|------|--------|
| Windows | 运行 `rxycode-desktop-1.3.0-setup.exe`（向导：默认目录、可 Browse、桌面快捷方式默认勾选），或解压 `RxyCode.Desktop-1.3.0-win.zip` 后运行 `rxycode-desktop.exe` |
| Linux | `chmod +x rxycode-desktop-1.3.0.AppImage && ./rxycode-desktop-1.3.0.AppImage`。没有 FUSE 时加 `APPIMAGE_EXTRACT_AND_RUN=1` |
| macOS | **本版不提供**安装包。请继续用 CLI / OpenTUI，或从源码 `npm run dev` |

装到 `~/.rxycode/desktop`（或设置 `RXYCODE_DESKTOP_DIR` / `--desktop-dir`）之后，**已经有 Desktop 的机器**才可以用 `rxycode gui` 当启动器。

**下载策略：** 仅本页（v1.3.0）提供当前 CLI sdist 与 Windows / Linux 桌面打包产物。v1.2.11 / v1.2.12 仍是 CLI-only 历史标签。更早的 Desktop 资源留在未关闭的 [v1.2.10](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10)。

## 资产 / Assets

- `rxycode-1.3.0.tar.gz`（CLI / OpenTUI 源码分发）
- `rxycode-desktop-1.3.0-setup.exe`（Windows 安装版：目录选择、预览、桌面快捷方式）
- `RxyCode.Desktop-1.3.0-win.zip`（Windows 便携版；解压后是 `RxyCode.Desktop-1.3.0-win/rxycode-desktop.exe`）
- `rxycode-desktop-1.3.0.AppImage`（Linux）
