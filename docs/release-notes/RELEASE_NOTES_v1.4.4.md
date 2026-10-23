# RxyCode v1.4.4

2026-10-22。产品版本 **1.4.4**。JSON-RPC 仍是 `1.1.0`。本次发布 CLI / OpenTUI 源码包；不发布新的 Desktop 安装包。

桌面安装包仍在 [v1.2.10](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10)。

## 安装

```bash
uv tool install --force --refresh "git+https://github.com/xin-yi33/RxyCode.git@v1.4.4"
```

或：

```bash
python -m pip install --no-cache-dir --force-reinstall rxycode-1.4.4.tar.gz
```

Windows：

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.4/install.ps1 | iex"
```

macOS / Linux：

```bash
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.4/install.sh | sh
```

## 这次的头条：RxyCode Web

同一套共享 Harness，多出一个浏览器入口：<https://rxycode.xyz>。

打开即用访客壳，发送时再登录；注册要邮箱验证码，登录可以在密码和验证码两种模式间按钮切换。注册、登录、找回密码三个入口都走 ALTCHA 工作量证明 + 每邮箱 5 分钟 5 次发码上限 + 每 IP 每小时注册封顶。一个账号同一时间只在一个设备上使用，别处顶号会收到「设备正在使用」的明确提示而不是静默失效。

模型侧是 BYOK：在设置页加密存放自己的 key（AES-256-GCM），发现模型、批量添加、测试连通性都在界面里完成；输入框旁直接选模型，切换有明确提示。会话页有工作区文件面板（列表 + 下载）、Markdown 渲染、工具卡片和可折叠的思考链。移动端按 390px 视口做了适配。

> 公网实例跑在一台资源有限的 VM 上，目前处于早期阶段——欢迎体验，但请对偶发的慢和重启有心理预期。

## 配对本机：`rxycode connect`

云端沙箱永远碰不到你的真实机器——需要操作本机文件时走显式配对的设备桥：

```bash
rxycode connect --url wss://<站点>/api/v1/devices/socket --code <一次性配对码> --device-id <名字> --capability shell
```

本机主动外拨 WSS，云端把 bash 调用下发到配对机器；每条写命令先落进审批收件箱，批准后才执行，而且被本地沙箱约束在 connect 启动时的工作区根目录内。已在 Windows 上实测创建/改写/读回本机文件。

## 运维与隔离

- 多用户并行 = worker 副本数，生产钉死为 3（`RXYCODE_WORKER_REPLICAS` 可调）；每用户在途任务上限 1。
- run 落在 PostgreSQL（租约认领 + 事件持久化），Redis 只做 SSE 扇出。
- 每个 run 一个 userns 沙箱：只写自己的租户工作区、无外网、丢了 capabilities、no-new-privileges。
- 每日 pg_dump 单副本轮换备份已进 cron。
- 取消在排队态直通终态，不用等 worker 空出来。

## 这次修掉的硬 bug

- 设备调用缺 `call_id`/`attempt_id` 会掉进口志路径直接 500——现在端点自动铸合规关联 id。
- `core/session_runtime.py` 的嵌套包相对导入在 API 镜像的扁平布局下炸掉任何相对路径写——改成双布局兼容导入。
- 粘贴文本里的 C0/NUL 控制字符曾让 PostgreSQL 提交 500——现在 API 边界净化。

完整清单见 [CHANGELOG_v1.4.4](CHANGELOG_v1.4.4.md)。
