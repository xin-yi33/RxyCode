# Cloud 修复部署计划（2026-10-24，cloudfix 批次）

> 目标：把本工作树中 2026-10-24 的四个云端 Web 缺陷修复（附件读取 / question 卡 / 单选提交 / question 恢复崩溃）以**同一构建**部署到 VM `192.168.88.128` 的 `rxyprod` 栈，并在 `https://rxycode.xyz` 做真机验收。
> 本文只记录操作步骤与验收口径；密钥、密码、cookie 值一律不落盘。

## 0. 事实基线

- 生产栈：`docker compose -p rxyprod --env-file /opt/rxycode/.env -f /opt/rxycode/compose.yaml -f /opt/rxycode/compose.prod.yaml`。
- 部署前镜像（回滚目标）：
  - `rxycode-api:web-dfb6f356`、`rxycode-web:web-dfb6f356`、`rxycode-worker:web-52e6c7a8`（worker 本来就比 api/web 新一个提交）。
  - compose.prod.yaml 里 api/web/worker 是硬编码 tag；`migrate` 服务仍用 `${RXYCODE_IMAGE_TAG:-latest}`（.env 里是过期 tag），部署脚本会统一改写。
- 生产源码 = VM `/opt/rxycode/src` 的 dirty 工作树（与本地工作树一致），镜像由该树在 VM 上 `docker build` 而来；**不是任何单一 commit 的干净树**。因此本次部署：commit 记录修复，构建用完整工作树 + 显式 manifest 记录 WIP overlay。
- 备份 cron 已坏（`backup_pg.sh` 缺 +x，最后成功 dump 2026-10-21）；部署脚本自带的 compose/.env 备份不覆盖 DB。本次不动 DB schema，但部署前仍建议手动跑一次 `pg_dump`（见 §5）。

## 1. 本地（Windows）准备

1. 本地全量测试（见 `docs/release-notes/CHANGELOG_v1.4.5.md` 对应条目）：Python 目标套件 + `npm --prefix apps/web run typecheck` + `tests/web/w3/test_w3_question_card.py`。
2. 生成 manifest：`git rev-parse HEAD`、`git status --porcelain`、工作树相对 HEAD 的逐文件 sha256（排除 `.git/node_modules/dist/build/__pycache__/.venv`）。
3. 生成传输 tar（同排除项）：约 350-400MB。
4. 上传：tar → VM `/home/ruanxinyi/cloudfix/<tag>.tar`；`scripts/deploy-web-vm.sh` → `/opt/rxycode/.ops/deploy-web-vm.sh`（root, 700）。

## 2. VM 构建（不触碰运行中容器）

```bash
TAG=cloudfix-<sha8>-01; COMMIT=<sha8>
SUDO="echo 123456 | sudo -S -p ''"
# 1) 解包到独立 build 目录（不影响 /opt/rxycode/src）
mkdir -p /home/ruanxinyi/cloudfix && tar -xf /home/ruanxinyi/cloudfix/$TAG.tar -C /home/ruanxinyi/cloudfix/$TAG
# 2) 构建三镜像 + 写 manifest
$SUDO bash /opt/rxycode/.ops/deploy-web-vm.sh build "$TAG" "$COMMIT" \
  --dir /home/ruanxinyi/cloudfix/$TAG --manifest /home/ruanxinyi/cloudfix/$TAG.manifest
# 3) 只读检查
$SUDO bash /opt/rxycode/.ops/deploy-web-vm.sh status
```

构建前检查磁盘：`df -Pk /opt/rxycode` 需 ≥ `MIN_FREE_KB_BUILD`（≈2.9GB）；不足先 prune 旧 dangling 镜像（保留回滚目标）。

## 3. VM 部署（唯一变更 prod 的步骤）

```bash
echo 123456 | sudo -S -p '' bash /opt/rxycode/.ops/deploy-web-vm.sh deploy "$TAG"
```

脚本行为：备份 compose.prod.yaml + .env（root 600）→ 四处 image pin 改为同一 tag 且同步 `.env RXYCODE_IMAGE_TAG` → `compose config` 断言 → 单次 migrate（新 api 镜像）→ 依次重建 api → worker×3 → gateway（健康门）→ `/api/v1/version` + `/api/v1/auth/csrf` 校验。任一后置失败默认自动回滚到备份 pin 并重建旧容器（`AUTO_ROLLBACK=0` 可关）。

失败人工回滚：`deploy-web-vm.sh rollback [备份目录]`（恢复 compose/.env 后重建旧镜像；不自动降级 schema）。

## 4. 线上验收（真机浏览器，必须监控 console）

验收对象：`https://rxycode.xyz/app/s/<新会话>`，使用临时 ops 会话 cookie（部署后在 api 容器内铸造，验收后立即撤销并恢复 device_locks 原值；不修改用户密码、不删除用户会话）。

场景 A（上传文件 → 云端口具链）：
1. 新会话上传 `实验报告-第3章 HDFS分布式文件系统_测试.docx`（含 HDFS/NameNode/DataNode 正文），提示“读一下这份文件，用三句话总结，并说出第 3 章标题”。
2. 期望：`attachment.import` imported；工具卡 `ls` 显示**原始中文文件名**；`read` 返回抽取正文而非 ZIP 乱码；最终答案包含 HDFS/NameNode/DataNode；无 `run.error`。

场景 B（question 卡 + 单选 + 恢复不崩）：
1. 新会话提示“在继续前先用 question 工具问我：给我 4 个方向选项（A 总结 B 校对 C 查重 D 改格式），我选好后再继续”。
2. 期望：卡片选项竖排、`1. 2. 3. 4.` 与 payload 顺序一致；点第 2 项后**只有该项**显示“提交中…”，rest 保持 label；网络面板恰好 1 个 `POST .../questions`，body `answer` = 该选项 value；折叠行为“你的回答：<label>”。
3. 回答后 run 继续（状态不再 `failed`），事件流无 `WorkflowContractError` / `run.error`，最终正常收尾。

证据：截图（问题卡点击前后、最终答案）、浏览器 console 无 error（忽略 Cloudflare beacon 第三方噪声时也要记录）、API access log 中单次 POST、DB `run_events` 中 `question.resolved` answer 单值且无 `run.error`。

## 5. 回滚/善后

- 应用回滚：`deploy-web-vm.sh rollback`（见 §3）；镜像 `web-dfb6f356/web-52e6c7a8` 保留。
- 数据：本次无 schema 变更；部署前建议 `docker exec rxyprod-postgres-1 pg_dump -U rxycode rxycode | gzip > /opt/rxycode/backups/pre-cloudfix-<UTC>.sql.gz`。
- ops 会话：删除临时 `auth_sessions` 行（或置 revoked_at），恢复 `device_locks` 原有 token_hash/created_at/last_seen_at。
- 记录：`docs/deploy/OPS-LOG.md` 追加一条（含镜像 tag/digest、health、验收证据路径）；changelog 见 v1.4.5。
