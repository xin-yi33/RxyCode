# TUI 剪贴板附件 E2E 验收记录（2026-10-11；收尾更新至 2026-10-12）

## 当前结论

**最终真实 E2E：三轮独立完整轮次均 4/4 GREEN，所有场景 assertions（含 PDF/MP4 引用免责声明）通过。** `clipboard-e2e-20261012-092556` pytest 1 passed / 11.22 s；`clipboard-e2e-20261012-092620` 1 passed / 10.53 s；移除未接线 `sitecustomize` 后的 `clipboard-e2e-20261012-093143` 1 passed / 11.19 s，units 15 passed / 2.86 s。第三轮 clipboard restore/hash 成功、Bun/appserver/worker 三 PID exited、`reader_stopped=true`，有 13 个合成 provider requests；图像 PNG 为 32×24、RGB(23, 167, 91)。前两轮同样是有效产品行为证据；其空 `evidence/jsonrpc` 目录不构成证据，也不是 wire trace。父代理确认三轮 evidence bundle 位于 `primary artifacts/tui-clipboard-e2e-2026-10-12/round-1` 至 `round-3`，共 27 files / 478171 bytes，copy hash verified，无 CA keys/config/fixtures。三处外部源目录仍完整未删：两次原生 `Remove-Item` 均被执行层 policy 拒绝；没有尝试其他 shell。残留路径见下文。worktree 将在父流程 commit 后通过 Git 原生 `worktree remove`；当前尚无 Git commit/hash。本次仅收尾文档与已授权的 provider EOF 空行修正，没有运行测试、操作剪贴板或删除目录。

工作树基线：`8823266ee45689876f2309555eee8184178dadfc`。父代理并行修改的产品文件不属于本验收实现，也未在本轮改动。

| 检查项 | 本轮状态 | 证据/边界 |
| --- | --- | --- |
| Python 文件语法解析 | 历史阶段通过 | 当时 8 个新增 E2E Python 文件完成 AST 解析；其后确认未生效的 `sitecustomize.py` 已删除 |
| 嵌入的 PowerShell 语法解析 | 通过 | 使用 PowerShell parser 解析 broker 脚本；没有执行脚本或访问剪贴板 |
| broker fake-backend 安全回归 | 通过（纯内存；以实际命令结果为准） | 覆盖备份异常/nil/unknown/incomplete、格式计数不一致的脱敏诊断、ownership 丢失、任意序列变化下精确恢复、空快照证据；不访问 OS 剪贴板 |
| PowerShell helper 启动探针 | 通过 | Windows STA helper 用 runtime `.ps1 -File` 启动；只发 `ping`/`quit`，没有发 snapshot，也没有读写剪贴板 |
| opt-in 未设置时的 pytest collection | 按设计跳过 | 输出为 1 个模块级 skip，未运行测试；pytest 因没有收集到测试返回 exit code 5 |
| loopback HTTPS provider TLS 自检 | 通过（本地） | 临时测试 CA、只给测试子进程的信任配置；未改系统信任库，无外网模型调用 |
| 真实 ConPTY / appserver / AgentV2 / OS 剪贴板链路 | **4/4 assertions GREEN，三轮独立运行** | 三轮各自完整通过全部场景及 disclaimer assertions，每轮 13 个合成 provider requests。第三轮 files chip/final 176.23/3460 ms，image 214.43/303.09 ms，text 188.91/303 ms，PDF/MP4 refs 188.2/318.32 ms。图像 PNG 32×24，RGB(23, 167, 91)。 |

## 四个真实复合场景与验收设计

以下编号保留四个场景的验收设计。三个独立最终轮次均对四项全部断言通过：1）文件/read；2）图像；3）text/link/bracketed-paste；4）PDF/MP4 仅文件引用且 Final 含完整免责声明。

1. **三轮均通过。** 多文件 `CF_HDROP`（含中文和空格文件名）→ `Alt+V` 附件 chips → 用户提示 → AgentV2 发出真实 `read` 工具调用 → 合成 provider 验证工具结果后返回 Final。
2. **三轮均通过。** `CF_DIB` bitmap → TUI 附件 → 实际发送的 PNG data URL → 本机 TLS control provider 解码并核对 32×24 尺寸及 RGB(23, 167, 91) 像素 → provider 预设 Final。provider trace 只留摘要/hash，不落盘图像 base64；这验证数据链路，不评估模型视觉能力。
3. **三轮均通过。** Unicode URL 剪贴板文本 `Alt+V` → bracketed 多行终端粘贴 → ConPTY 的 LF（Shift+Enter 表示）→ Enter 提交；provider 请求断言各标记只出现一次。
4. **三轮均通过。** PDF 与 MP4 `CF_HDROP` → 仅文件引用进入请求 → provider request 不含 image payload，PDF/MP4 仅作引用；Final 含完整免责声明。这不是对真实模型诚实性/文档理解能力的评估。

**阶段性采证根因（已修复并由最终三轮覆盖）：** 终端增量 ANSI cursor movement 会跳过空白 cells，纯剥 CSI 后曾得到 `onlyfilereferencesweresupplied`（无字面空格）；完整词句仍实际存在，raw-ANSI TUI render 是完整 Final，并非产品隐藏。claimer 已改为在同一 70 秒 deadline 内等待完整 ASCII 序列并做 ANSI/空白归一化；缺词仍失败，并补了回归测试，没有新增 VT。最终三轮 4/4 均通过。

证据层级说明：验收证据是 ConPTY 的真实增量文本观察、持久化 appserver `task-events.json` 事件，以及 provider/data assertions；这不等于完整 JSON-RPC wire capture。图像的 32×24 RGB 核验是 provider 收到的 PNG payload 像素检查，不是 TUI 截图像素审核。本轮没有做 UI pixel-level visual review。源码检查确认入口链为 `rxycode.exe → main._launch_opentui → src/index`；无需 dist build，真实 E2E 直接启动同一份 source，因此不代表从外层 `rxycode.exe` 实际启动的 E2E 验证。

**JSON-RPC 采证纠正（2026-10-12）：** 曾尝试用测试子进程 `sitecustomize.py` tee 完整 JSON-RPC，但生产 `stdioTransport.start` 固定以 `this.projectRoot()` 设置 `PYTHONPATH`，覆盖 harness 加入的 `tests/e2e/clipboard_attachments` 路径，因此该 `sitecustomize.py` 实际未被导入。前两轮的 `evidence/jsonrpc` 目录为空，不能声称采到了完整 wire trace；这些空目录不是证据。已删除这个未发布、未生效的钩子，并从 harness 移除 `RXYCODE_CLIPBOARD_E2E_RPC_TRACE` 和空目录创建；生产传输未改。死钩移除后的 fresh units 15 passed / 2.86 s，第三轮真实 suite 4/4、pytest 1 passed / 11.19 s。有效证据是 appserver 持久 `task-events.json` 协议事件、provider trace 和 terminal 观察，仍不等于完整 wire capture；三轮产品行为 assertions 均通过。

第三轮 chip/final 延迟（ms）：files 176.23/3460，image 214.43/303.09，text 188.91/303，refs 188.2/318.32。前两轮计时保留在 run 表。100 ms 指标衡量最终 chip 完成时间，不是刚开始读取剪贴板时的状态反馈；图像处理约 214 ms，因此不能声称全部场景达到 100 ms。

队列快照、移除/清空附件、dialog 不污染主 draft、session 切换/迟到 paste、text-only 模型拒绝图像和失败后恢复等边界不冒充为这四个 ConPTY 场景的覆盖；应由并行前端 native-unit/契约测试单独验收，并在新报告中注明测试层级与结果。

## 父代理提供的非 E2E 回归快照

以下结果对应各自冻结快照，不等于四场景 E2E 通过，也不是全仓库全绿：

- core/appserver/bridge/cache/protocol/packaging：8516 passed / 4 skipped / 2 deselected，448.93 秒。两个未通过项均在干净 master 基线 `8823266e` 复现：根 docs 中旧 CLI-memory 报告触发 `tracked_docs_allowlist`；`backfill_missing_api_key_secrets_from_env` 在全 core 顺序中返回 0、隔离运行通过（基线全 core 跑至 272 passed 后也复现）。
- OpenTUI fresh Bun：384 passed / 0 failed，`tsc` 通过；protocol：29 passed，`tsc` 通过。
- dead-hook 移除后的 fresh provider + broker units：15 passed / 2.86 s（含 missing-word 必须失败）；fresh all-feature suite：60 passed / 2 skipped / 5.90 s；fresh Bun：384 passed / 31.76 s，`tsc` 通过；protocol/codegen：29 passed，`tsc` 通过。其他既有快照：Python focused 113 passed / 2 skipped；packaging/schema 25 passed / 1 deselected；providers/tools/subagents/schema 2162 passed。以上是各自范围/快照，不能相加成整体通过数。
- 较早冻结 broad gate 保留原 scope：8516 passed / 4 skipped / 2 deselected；两项基线问题不与后续 focused 结果叠加，也不表示全仓库全绿。

三轮真实 suite 的用例级运行结果及 latency 见下方 run 表；每轮 13 个合成 provider requests，未调用 live model。usage 均为合成值。

## 安全与隔离

- pytest 用现有 `serial`、`pty`、`e2e` 标记；入口要求调用者事先显式设置 `RXYCODE_CLIPBOARD_E2E=1`，拒绝 pytest-xdist worker 参数，并通过 Windows 命名 mutex 阻止另一个 opt-in suite 进程并行运行。一般 pytest gate 不会自动改剪贴板。
- helper 脚本按唯一文件名写入本轮 artifact/output 目录，以短 `-File` argv 启动；不把脚本 base64 塞入 CreateProcess 命令行。命令行 UTF-16 长度含终止符需小于 32767；`-ExecutionPolicy Bypass` 仅为该子进程参数，不持久修改用户/机器策略。
- 剪贴板 broker 先在一个 STA helper 中复制所有可识别格式到进程内备份，并比较格式集合和内容 digest；Python 端也校验 snapshot schema。helper 未完成备份前只能 `ping`/`quit`，snapshot 失败时构造关闭该 helper，不调用 restore 或 `SetDataObject`。
- 记录 `GetClipboardSequenceNumber()` 的原始序列和每次写入后稳定读回的实际序列与摘要，不假设 API 一次调用只递增 1。每次写入前核对当前 owned sequence；写入后核验实际 fixture payload 与稳定快照，才接管新序列。恢复前再次核对序列和测试 payload；至多调用一次 `SetDataObject`/`Clear`，再以稳定快照核验原摘要。
- 一旦确认外部 ownership 变化即中止、不再 restore 旧快照，并关闭本轮专属 helper；证据状态为 `external-modification`、`clipboard_restored=false`。只有原格式摘要与内容 digest 完全一致才记录 `restored`。恢复失败保持 `restore-unverified`，不得记为 clean/pass。
- 空剪贴板只有在序列非零、原生格式数为零且 Win32 调用成功、序列/格式数稳定，并有规范空摘要时才接受；未知/null 不作为空快照。
- `GetClipboardSequenceNumber` 检查与系统剪贴板写入不是 Windows 提供的原子 compare-and-swap；极短的并发窗口仍是平台边界。报告会以实际恢复校验和序列证据为准，绝不把外部变化写成 restored。
- runner 子进程使用隔离的 workspace、data/config、HOME/USERPROFILE、skill roots；真实用户 skill roots 不会进入本地 provider 请求。API key 为合成环境变量；child 环境移除现存 credential/proxy 类变量。
- provider 只绑定 `127.0.0.1`，使用每次运行临时生成的 TLS CA/证书，TLS 信任只注入测试子进程。最终视觉 fixture 配置为 `gpt-5.6-luna`，但回答由本地 synthetic control provider 决定，不表示真实模型理解或真实模型诚实性。usage 是合成值，不作为真实模型 token/cost 数据。
- evidence 包含 ANSI 终端输出、纯文本 chunk、脱敏 provider trace、持久化任务 Final/tool 事件、清理 PID 和剪贴板摘要；**没有完整 JSON-RPC wire trace**。不保存原用户剪贴板值或图像内容。每次运行写入唯一目录，不自动删除既有证据。

## 真实尝试记录与剪贴板安全状态

以下均为父代理协调的真实 Windows suite 启动；这份报告未自行启动或重跑任何真实剪贴板操作。

| Run | 结果与失败根因 | Broker 安全事实 |
| --- | --- | --- |
| `clipboard-e2e-20261011-232559` | 首次正式运行在 snapshot backup verification 失败。 | 当时没有 `clipboard-safety.json`：构造异常路径只关闭 helper，没有保存 stage/error metadata。父代理确认未写入测试剪贴板；该轮缺少足够证据来报告已恢复。 |
| `clipboard-e2e-20261011-233058` | 再次在 snapshot 失败；脱敏证据为 `System.Management.Automation.RuntimeException`，stage=`snapshot-hash-content-signature`，`ready=false`。 | 只执行 `snapshot`，没有写入或恢复。后续 PowerShell 5.1 内存 IDataObject 对 UnicodeText 单格式、UnicodeText+HTML 双格式、空对象的 `Get-Snapshot → Copy → Get-Snapshot` 复现均成功；这不证明当时真实剪贴板的格式内容可被安全复制。 |
| `clipboard-e2e-20261011-234547` | 普通文本备份成功；首场景发送 Alt+V 后，1 秒内未观察到 `材料 一号.txt` chip，output tail 为空，场景未提交。 | `clipboard-safety.json` 为 `ready=true`、`restored=true`、无 external modification；记录 `snapshot → set_files → restore`。终端 chunks 无目标 chip、无“读取剪贴板…”或“已添加”提示；该份 E2E 证据不包含规范化 native key 事件或 `set_files` 耗时，故不能断言是热键解析还是 helper 延迟。首帧 placeholder 不是 session warm 就绪证明。 |
| `clipboard-e2e-20261011-235418` | 当次 Alt 修复后运行触发 standalone clipboard helper，但 helper exit code 1；直接执行时 `import queue` 被仓库 `utils/queue.py` 遮蔽并触发相对导入错误。此后已改用 `-I -X utf8` 隔离并以真实 `--help` 回归；该历史失败不代表当前 helper 状态。 | `clipboard-safety.json` 记录 `ready=true`、`restored=true`、无 external modification，操作为 `snapshot → set_files → restore`。但同目录 `acceptance-summary.json` 的 `clipboard_restored=false` 与 safety 文件的 restored 状态冲突；因此保留该矛盾，不能把它静默归并为一致。 |
| `2026-10-12 09:10:17` historical fresh 4-suite | 当时 3/4 全 assertions 通过，第四场景 raw-ANSI capture false negative；根因与修复见上。 | 用户配置保持原状；剪贴板恢复 hash 校验通过。 |
| `clipboard-e2e-20261012-092556` | pytest 1 passed / 11.22 s；4/4 场景全部 assertions 通过，包括 PDF/MP4 完整免责声明。各场景记录 timing：files 170.32 ms、image 210.87 ms、text 188.75 ms、refs 190.51 ms。每轮 13 个合成 provider requests。 | `clipboard_restored=true`，恢复 hash 与备份一致；用户配置未改；Bun/appserver/worker 三 PID 均 exited，`reader_stopped=true`；5 formats。 |
| `clipboard-e2e-20261012-092620` | pytest 1 passed / 10.53 s；4/4 场景全部 assertions 通过，包括 PDF/MP4 完整免责声明。chip/final timings（ms）：files 98.29/3120.44，image 220.91/302.01，text 189.14/301.76，refs 191.59/301.09。每轮 13 个合成 provider requests。 | `clipboard_restored=true`，恢复 hash 与备份一致；用户配置未改；Bun/appserver/worker 三 PID 均 exited，`reader_stopped=true`；5 formats。 |
| `clipboard-e2e-20261012-093143` | 移除 dead-hook 后 pytest 1 passed / 11.19 s；4/4 场景全部 assertions 通过，包括 PDF/MP4 完整免责声明。chip/final timings（ms）：files 176.23/3460，image 214.43/303.09，text 188.91/303，refs 188.2/318.32；每轮 13 个合成 provider requests。 | `clipboard_restored=true`、恢复 hash 一致；Bun/appserver/worker 三 PID exited，`reader_stopped=true`；图像 PNG 32×24、RGB(23, 167, 91)。 |

2026-10-12 中间阶段核验：新版 broker 的 backup-failure 记录明确为 **0 writes / 0 restores**。用户主动复制普通文本后，当时一组运行备份 7 种格式并验证 restored hash 一致。前两轮各备份 5 种格式，第三轮亦验证 clipboard restore/hash 成功；中间 7 formats 记录不替代最终三轮证据，也不改变更早旧预检缺原 digest、无法确认是否精确恢复的结论。

另有更早的一次序列号保护完成前的 opt-in 预检：可确认的调用链是 `ClipboardBroker(...)` 的上下文退出进入 `__exit__()` → `restore()` → helper `restore` 分支 → `Clipboard.SetDataObject($Backup, $true)`；该预检没有测试写入，却仍进入 restore；当时 restore 清理没有要求先发生过测试写入，且旧 Python 端没有验证完整 snapshot schema。该轮缺少原内容 digest，**不能确认是否精确恢复**；也不能据此声称数据丢失。早期 managed clipboard 无法校验的具体原因没有证据，不作推测。父代理随后只读观察到 sequence 647、native format count 2、sequence 稳定；没有读内容或写入。此前对“空剪贴板”的描述也不能作为恢复证据。

上述早期失败运行的 artifacts 曾位于 `D:\tmp-cursor-probe\rxycode-clipboard-acceptance-20261011`，不作为当前通过证据。三轮 evidence bundle 位于 `primary artifacts/tui-clipboard-e2e-2026-10-12/round-1`、`round-2`、`round-3`，共 27 files / 478171 bytes，copy hash verified，无 CA keys/config/fixtures。前两轮空 `evidence/jsonrpc` 目录不是证据；bundle 中的有效材料为 terminal、持久化 task events、provider 与安全摘要，不含完整 JSON-RPC wire trace。以下三个外部源目录仍完整未删，两次原生 `Remove-Item` 均被执行层 policy 拒绝，没有尝试其他 shell 绕过：`D:\tmp-cursor-probe\rxycode-clipboard-acceptance-20261011`、`D:\tmp-cursor-probe\rxycode-clipboard-snapshot-readonly`、`D:\tmp-cursor-probe\opencode-clipboard-ref-20261011`。worktree 将在父流程 commit 后使用 Git 原生 `worktree remove`；当前未 commit。剪贴板证据不记录原始用户文本；以上仅引用状态、操作名、序列、stage 和错误类别。每轮的安全状态仅适用于该轮 snapshot 与 restore，不能反推更早预检是否恢复了当时未知的原始内容。

历史阶段的 **1/4** 与 09:10:17 的 **3/4** 快照均保留在时间线；随后三个独立 fresh run 已各自完整 **4/4 GREEN**，覆盖并取代这些阶段状态。第三轮在死接线移除后复核通过。09:10 的 ANSI/空白采证 race 已修复并有回归；没有放宽缺词断言或增加 VT。

## 本轮新增文件

- `tests/e2e/clipboard_attachments/clipboard_broker.py`：STA 备份、摘要、序列所有权与恢复验证。
- `tests/e2e/clipboard_attachments/provider.py`：loopback TLS OpenAI-compatible control provider 和脱敏/图像摘要 trace。
- `tests/e2e/clipboard_attachments/harness.py`：隔离运行时、checkout 导入来源核验、ConPTY 捕获和精确子进程清理。
- `tests/e2e/clipboard_attachments/test_clipboard_attachments.py`：四个真实复合场景及最终验收断言。
- `tests/e2e/clipboard_attachments/test_clipboard_broker_unit.py`：fake-backend 失败关闭回归和不触碰剪贴板的 helper `ping` 启动探针。
- `tests/e2e/clipboard_attachments/runner.py`：要求显式 opt-in 的手动入口。

## 手动运行（仅在启动前已提醒用户后）

从工作树根目录在 PowerShell 单进程环境运行；该入口不会自行设置 opt-in：

```powershell
$env:RXYCODE_CLIPBOARD_E2E = '1'
try {
  python tests\e2e\clipboard_attachments\runner.py --output-root D:\tmp\rxycode-clipboard-e2e
} finally {
  Remove-Item Env:RXYCODE_CLIPBOARD_E2E -ErrorAction SilentlyContinue
}
```

若本机 `bun` 不能解析为原生 `.exe`，可在启动前将 `RXYCODE_CLIPBOARD_E2E_BUN` 指向已验证的 Bun `.exe`；Python 默认使用当前 `python`，也可通过测试专用 `RXYCODE_CLIPBOARD_E2E_PYTHON` 指定。运行后应把实际 scenario 结果、`clipboard-safety.json`、`acceptance-summary.json`、provider/terminal/task trace 与 PID 清理情况补到本报告。若 evidence 状态为 `external-modification`，保留当时剪贴板，不尝试恢复旧快照，并将该轮标为中止而不是通过。
