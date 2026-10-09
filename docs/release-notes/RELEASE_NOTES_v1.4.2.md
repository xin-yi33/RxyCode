# RxyCode v1.4.2

日期：2026-10-09。
这是 CLI / OpenTUI 版本，不发布新的 Electron Desktop 安装包。

## 本次变化

- Todo：`todo_write` 复用现有 `tasks.json`，保存完整快照；旧
  `task` / `task_manage` 保留兼容入口。成功写发 `event/todo_updated`，
  `todo/get` 从同一台账读当前状态。
- OpenTUI：输入区上方展示 Todo，`Ctrl+T` 展开或收起，`Ctrl+E` 切换思考。
  空清单清除旧投影，其他会话或过期 revision 不覆盖当前清单。
- 模型侧状态带：fast / graph 共用渲染器，从权威快照读取进度。
  当前请求已经含最新状态时不重复贴；压缩后恢复必要状态。
  读取、显示和恢复 Todo 不额外调用模型总结。
- 压缩：旧摘要与新增折叠内容合并；模型失败有规则降级。
  自动摘要反复失败或上下文反复回满时停止重复消耗；手动 `/compact` 仍可用。
- 大输出：bash 在第一次截断前落盘，保留预览和绝对路径指针；
  敏感内容清洗与工具输出预算仍有效，压缩墓碑保留可读回路径。
- 长任务：统一超时配置，默认关闭的超时决策可以按策略
  continue / steer / stop；续期、取消、进程回收、事件和成本有明确约束。
- Fix4：分级 stall 恢复、有限 checkpoint resume、项目隔离的 memory
  flush / recall、schedule dispatch 恢复，以及 prompt version 缓存键接线。
- 发布审计补缺：修复预热子任务取消其父任务的递归取消，保留真实用户请求取消预热的能力；
  worker 在读取请求前设定 UTF-8，避免 Windows 中文 prompt 损坏和 checkpoint 失败。
- 安装包补齐协议 schema、运行时版本清单、模型目录和内置子代理定义；
  验收从独立安装目录读取这些资源，不用源码存在来替代安装可用。
- 无密钥输出先做候选检查，避免逐字脱敏扫描；有候选字段仍用原解析器。
  原有 200ms 性能门槛和跨行、引号、转义、大小写清洗断言保留。

## 安装

本 tag 只发布 `rxycode-1.4.2.tar.gz`。GitHub 自动生成的源码 zip/tar.gz
不是开箱即用的 Desktop 安装包。

```powershell
uv tool install --force --refresh "git+https://github.com/xin-yi33/RxyCode.git@v1.4.2"
rxycode --version
rxycode
```

或下载该 Release 的 tar.gz 后：

```powershell
python -m pip install --no-cache-dir --force-reinstall rxycode-1.4.2.tar.gz
rxycode --version
```

### 同版本替换后的升级

如果你在本次同一 `1.4.2` tag / tarball 替换前已经安装过 `v1.4.2`，必须刷新缓存并重装，不能只依赖版本号判断已是最新。uv 使用上面的 `--force --refresh`；本地 tarball 使用上面的 `--no-cache-dir --force-reinstall`。

产品版本是 `1.4.2`；JSON-RPC 兼容版本仍是 `1.1.0`；
Python 导入路径仍为 `RxyCode.RxyCode1_1_0`。不修改历史版本目录和第三方依赖版本。

## 真实边界

- Todo 的 completed 是计划状态，不代替工具、文件或测试证据。
- 状态带进入模型上下文仍消耗 input token；只保证不另起 Todo 总结调用，
  不承诺所有模型、冷请求或压缩后都达到 97% 缓存命中。
- P8 新状态带到超时证据的生产消费现已补齐：pipeline、graph watchdog、
  ToolOrchestrator tool timeout 和 AppServer stall recovery 四个生产入口，
  均从当前 session 的权威 `TodoSnapshot` 读取最新 progress。空、坏或身份/
  scope 不符时只产生空 progress；有效持久快照可让重建后的消费方恢复最新
  progress。读取和恢复不调用额外 Todo-summary 模型。
- 外层工具续期不能改变 shell 自身的内部 deadline（R-11）。
- scheduler 恢复 dispatch 不等于无人窗口自动执行 prompt。
- 超时决策默认关闭；关闭分支是有效兼容路径，不是废弃代码。
- OS sandbox 继续默认关闭。Windows Job Object 管资源与进程树，
  不是完整文件系统/网络边界；本次不声称 Linux/macOS 原生执行已实机验证。
- 不发布 Desktop 二进制；仅同步其产品元数据。

## 验证记录

本轮本地五层验收：unit 231、integration 7、contract 873、serial 8、
legacy regression 12320，共 **13439 passed / 28 skipped**。
跳过项为 26 项未发布计划树检查、1 项显式 live 开关测试、1 项重复 query 样本。
收尾修改另跑 API / SSE / 真实安装回归 **68 passed**。
脱敏性能修复后，工具/恢复/投影联合复测 **94 passed**；
实际采集 coverage 的脱敏与 spill 组 **17 passed**，200ms 原门槛通过。

前端：OpenTUI **314 passed**，protocol-client **29 passed**，Ink **1502 passed**；
typecheck、协议生成物检查和 build 通过。真实 Windows ConPTY 为
**19 项交互 + 2 项异常退出**通过，OpenTUI `/model`、`/mod` Enter 通过。
Node 24 的 ConPTY helper 打印 `AttachConsole failed`，但本轮交互和退出判据通过；
该警告不冒充无告警结果。

ruff、秘密扫描、README 双语同步检查、版本/安装契约和
Windows 原生沙箱 22 项通过。GitHub 平台 CI 与正式 tag 的构建、Linux/Windows
安装 smoke 由 [Actions](https://github.com/xin-yi33/RxyCode/actions) 记录；
本地结果不替代 hosted 结果，也不替代 live 模型性能评测。
逐项生产路由、命令、结果与限制见
[完成审计](V1.4.2-COMPLETION-AUDIT.md)；
历史开发过程见[详细 changelog](CHANGELOG_v1.4.2.md)。

## P8 补缺记录

原始 1.4.2 打包状态遗漏了上述 P8 生产 evidence consumer；本节记录同一
1.4.2 release line 的补齐，不创建新的产品版本。实现复用现有
`protocol.todo.TodoSnapshot`、`tasks.json` reader 与确定性 session/root/list/scope
校验，不新增 protocol model、Todo store、timeout 默认值、预算或 shell 内部
deadline 行为。

验收记录见 [`P8/FIX5 handoff acceptance`](../P8-FIX5-HANDOFF-ACCEPTANCE.md)。
P8 专项回归 `112 passed`，不重复计入主审全量 `13463 passed / 28 baseline
skipped`；云端 CI 与正式 Release 资产仍需按发布流程独立复验。
