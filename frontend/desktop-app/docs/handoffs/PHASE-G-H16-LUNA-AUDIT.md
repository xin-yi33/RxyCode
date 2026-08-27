VERDICT: PASS

- **档位来源**：`effortOptions` 对应 `effort_options`，select 以其作为可选档位。
- **无档位禁用**：`disabled={effortOptions.length === 0 || activeModel === null}`，满足无档位或无活动模型时禁用。
- **提交带 effort**：变更时调用 `models.setActive(id, event.target.value)`；`requestSetActive` 通过 `models/set_active` 提交 `{id, effort}`。
- **全局设置一致性**：
  - `ModelsSnapshot.effort` 从 `models/list.effort` 读取，空字符串等无效值归一为 `null`。
  - select 的 `value` 使用 snapshot 中的 effort，并校验其存在于当前 `effortOptions`。
  - set_active 成功后执行 `refresh()`，保持全局状态同步。
- **空 effort 处理**：`buildSetActiveParams` 对空、`null`、`undefined` 省略 `effort`，有档位时保留 `{id, effort}`。
- **请求行为**：使用 `request('models/set_active', params, 30000)`，仅 `ok === true` 判定成功；测试覆盖了带 `effort` 的请求参数。