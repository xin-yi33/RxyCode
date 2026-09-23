# Phase G 分支（不要再互合并）

以前增强卡写「从 master 开 `feat/gxN`，前后端挤在同一分支再 squash」。
你已经有 `feat/phase-g-backend` 和 `feat/phase-g-frontend`，再开第三套分支只会：

1. 把增强和没增强的历史拧在一起  
2. 再跟 master 解一轮冲突  

## 以后就这样走

```text
master
  ├─ feat/phase-g-backend     只改 appserver / protocol / tests/*.py / docs/phase-g/backend/
  └─ feat/phase-g-frontend    只改 frontend/desktop-app / protocol-client 消费 / docs/phase-g/frontend/
```

- **不要** `git merge feat/phase-g-frontend` 进 backend，反过来也不要。
- **不要**为每张 GX 再开 `feat/gxN`。
- 联调只用 `feat/phase-g-integrate`（从 master 开，先合 backend 再合 frontend）。不要把 frontend merge 进 backend。
- 两端各自 PR 进 master。schema 由后端先合；前端等 schema 在 master（或 cherry-pick 那一次协议 commit）后再接 UI。
- 公共基线 `PHASE-G-DESKTOP.md` 当只读。真要改产品定义，单独一个文档 PR，不要夹在施工 commit 里。

## 卡怎么对应

G1–G16 主链早就拆成 B/H。增强 GX1–GX28 现在同样拆成：

- `GXN-B` = 协议 + appserver（后端文档）
- `GXN-H` = Desktop UI（前端文档）
- 纯前端卡（GX1/GX6/GX10…）没有 B 卡
