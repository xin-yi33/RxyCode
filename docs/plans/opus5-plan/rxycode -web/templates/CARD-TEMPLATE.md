# WEB-Wx-Cyy · <唯一标题>

`优先级:P0/P1` / `预计工时` / `依赖:WEB-W...` · **owner: backend/frontend/protocol/security/ops**

**调研原文与真实当前事实**：引用已确认 path、完整唯一 Grep 锚点、上游版本/commit、功能存在/不存在的负向证据；不能写“应该已经有”。

**涉及文件（白名单）**：文件 | Grep 锚点（新建则 NEW） | 具体改法。任何表外文件先 STOP。

**已经替你决定好的**：模型/DTO/协议方法/错误码/权限状态机/代码骨架/是否兼容旧接口/为什么不用另一方案，一律写死，不让执行者猜。

**操作步骤**：1. LOCATE & PRECHECK；2. RED Unit/Module/Negative；3. 实现核心；4. 接 JSON Schema/TS；5. Process/E2E；6. Audit & handoff。

**单元测试**：固定 `tests/web/wx/test_wx_cyy_unit.py::test_wx_cyy_contract`。Given / When / Then，assert 值、触发路径及禁止行为。

**模块测试**：固定 `tests/web/wx/test_wx_cyy_module.py::test_wx_cyy_integration`，必须跨真实模块/进程边界。

**反向测试**：固定 `tests/web/wx/test_wx_cyy_unit.py::test_wx_cyy_negative`，必须覆盖拒绝、重放/错误/冲突。

**Process/E2E**：本卡适用时指定 `E2E-*` ID、真实启动方式和保留日志；不适用要写原因与由哪一张总门承接。

**验收命令（Windows PowerShell）**：`rg -n` + 指定测试文件 + schema/缓存/构建门（按涉及模块）+ `git diff --check`。新文件不存在必须由本卡创建。

**完成判据**：所有指定 tests 真绿/0 无理 skip；没有回归；有 evidence 的 RED/GREEN、diff、协议和 negative；Human Review PASS；一张卡一个 Commit。

**Commit**：`feat(web): web-wx-cyy - <为什么>`。
