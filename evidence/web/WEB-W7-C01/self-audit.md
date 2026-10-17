# WEB-W7-C01 self-audit

- [x] Routes reviewed for `current_record`/`require_write`/tenant filters: all
  surfaces in handoff.md table hold; attacker sees 404/403, never data.
- [x] `grant_store.py` verified: every evaluate() audits; all seven refusal
  codes exercised by tests (4 in threat file + GRANT_REQUIRED in negative;
  GRANT_EXPIRED/GRANT_REVOKED covered by existing W4 tests re-run this card).
- [x] Frozen decisions hold: backend enforcement, unknown tools refused,
  Remote Full requires real grant, logs redacted, sandbox fail-closed.
- [x] One real P1 found and fixed inside the whitelist ruling:
  `Set-Content`/`Add-Content` positional-path bypass of the write-path gate.
  Fix is the minimal lookbehind; no refusal behavior loosened.
- [x] RED captured honestly: `2 failed` (P1 bypass + my unpack bug).
- [x] GREEN (current, see green.txt, audit round 27 code): card tests
  w7 unit + module + security/test_threat_model 10 passed; safety files
  (test_safety_policy/api/audit/gate) 200 passed; cache regressions
  30 passed, 2 skipped (pre-existing); ruff clean. The first GREEN at
  card commit 174f345c was 9/9 card tests, policy+cache regressions 168
  pass, W4 grant tests 3 pass.
- [x] Honest labels: Demo-compose identity audit and E2E-SECURITY-01 marked
  BLOCKED_PREREQUISITE/BLOCKED, not passed. No screenshots claimed. No mock
  tool events.
- [x] `git diff --check` clean; LF endings on evidence.
- [x] Audit verdict: gpt-6-luna max (Codex session
  01a140a7-2cc1-7f61-bdab-2af627f08e80) returned VERDICT: NO_REMAINING_PROBLEMS
  for parent commit a6e8fa56f3bf3324f26ba3b5dbd6a24dbd943183 (w7c01-audit-30.json).
  From round 24 on, the write-path gate was accepted against the frozen corpus,
  per nested rulings c9dc4d86 / f011d1cc. Remaining gate limitations are listed below.

## 已知限制（写路径闸，非阻塞）

依据嵌套仓裁定 c9dc4d86：Full 是用户确认后在当前账户权限内解除沙箱，写路径闸在 Full 下只是尽力而为的防误写闸，不是安全边界；普通模式的写隔离由 OS 沙箱承担（Windows 写隔离另开卡）。下列写法由第 23 轮审计（w7c01-audit-23.json，审计对象 46701915）发现，按冻结语料口径记为已知限制，不在本卡修复：

1. PowerShell 命名位置栈（`Push-Location -StackName`/`Pop-Location -StackName`）按单一栈跟踪；`-StackName` 在 `-Path` 之前时会把栈名当成目标。
2. `Set-Location HKCU:\…`、`Set-Location Env:` 等 provider 路径被当成工作区子目录，其后的 `New-Item`/`Set-Content` 写注册表或环境变量不被拒绝。
3. 经 `cmd /c call x.bat`、`cmd /c start x.bat`、`Start-Process -FilePath x.ps1` 启动的脚本文件，以及依赖 PATHEXT 的无扩展名脚本（`cmd /c evil`），不被当作脚本文件载荷。
4. 实现者自查发现：`node -e "require('fs').writeFileSync('C:/Windows/x','x')"` 这种不经变量绑定、直接在 `require('fs')` 上链式调用写 API 的形式不被识别（`const fs=require('fs'); fs.writeFileSync(...)` 和裸 `fs.writeFileSync(...)` 能拦下）。heredoc 喂给 node 的同类写法同样漏判。
5. 多拒（偏安全方向）：heredoc 归属按包装命令之后的全部 token 判定、不解析各包装命令的选项表，因此当选项取值恰好是 shell、解释器或执行器名时会多拒，例如 `env -u xargs cat <<EOF`、`env -u bash cat <<EOF`（第 28 轮审计 w7c01-audit-28.json 指出）。这是第 27 轮为消除选项表缺项导致的漏放而有意做的取舍。

第 24 轮审计（w7c01-audit-24.json）指出 Start-Process -WorkingDirectory 导致的白名单内误拒，已修复；原第 1、2 条限制随同修复，已从清单移除。

第 25 轮审计（w7c01-audit-25.json）指出 Start-Process 子目录归属误拒与 heredoc 只读误拒，均已修复；原第 4 条（heredoc 误判）已从清单移除。
