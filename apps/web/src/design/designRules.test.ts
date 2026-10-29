// 设计规范回归契约（bun test，无 DOM 依赖）：
//  1. isBackdropDismissClick 的真实判定逻辑 —— maskClosable=false 的表单
//     弹层点遮罩不得关闭（不丢未保存输入）。
//  2. 源码级不变量 —— 表单弹层 maskClosable={false}、二次确认
//     alertdialog + 危险按钮、验证码 one-time-code、抽屉锁背景滚动、
//     审批中立、accent token 通道、safe-area 兜底。
// 源码扫描是对行为单测的补充：防止后续改动悄悄退回旧交互。

import { describe, expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"

import { isBackdropDismissClick } from "../components/ui/dialog"

const SRC = fileURLToPath(new URL("..", import.meta.url))
const WEB = fileURLToPath(new URL("../..", import.meta.url))
const read = (rel: string) => readFileSync(`${SRC}/${rel}`, "utf-8")
const readWeb = (rel: string) => readFileSync(`${WEB}/${rel}`, "utf-8")

/** 假 <dialog>：内容盒 100..300 × 100..200。 */
const fakeDialog = () =>
  ({
    getBoundingClientRect: () => ({
      left: 100,
      right: 300,
      top: 100,
      bottom: 200,
    }),
  }) as unknown as Element

describe("遮罩关闭判定 isBackdropDismissClick", () => {
  const dialog = fakeDialog()
  const outside = { target: dialog as EventTarget, clientX: 10, clientY: 10 }
  const inside = { target: dialog as EventTarget, clientX: 200, clientY: 150 }

  test("maskClosable=false：点遮罩不关闭（表单弹层不丢输入）", () => {
    expect(isBackdropDismissClick(false, outside, dialog)).toBe(false)
    expect(isBackdropDismissClick(false, inside, dialog)).toBe(false)
  })

  test("maskClosable=true + 点在内容盒之外 → 关闭", () => {
    expect(isBackdropDismissClick(true, outside, dialog)).toBe(true)
  })

  test("点在内容盒内不关闭（穿透点击不冒泡关闭）", () => {
    expect(isBackdropDismissClick(true, inside, dialog)).toBe(false)
  })

  test("点击目标是子元素而非 <dialog> 自身时不关闭", () => {
    const child = { nodeType: 1 } as unknown as EventTarget
    expect(
      isBackdropDismissClick(true, { target: child, clientX: 10, clientY: 10 }, dialog),
    ).toBe(false)
  })

  test("无 dialog 引用时不关闭", () => {
    expect(isBackdropDismissClick(true, outside, null)).toBe(false)
  })
})

describe("表单弹层：遮罩点击不得静默丢输入", () => {
  test("共享 Modal 支持 maskClosable 并默认保持可关（只读层不受影响）", () => {
    const src = read("components/ui/dialog.tsx")
    expect(src).toContain("maskClosable = true")
    expect(src).toContain("isBackdropDismissClick(maskClosable")
  })

  test("共享 ConfirmDialog：alertdialog + 遮罩不可关 + danger 变体", () => {
    const src = read("components/ui/dialog.tsx")
    expect(src).toContain('role="alertdialog"')
    expect(src).toContain("maskClosable={false}")
    expect(src).toContain('variant={danger ? "danger" : "default"}')
  })

  test("Button 具备 danger 变体（实心 failure，仅二次确认使用）", () => {
    const src = read("components/ui/button.tsx")
    expect(src).toContain("danger:")
    expect(src).toContain("bg-failure")
  })

  test.each([
    "features/settings/ConnectionFormDialog.tsx",
    "features/console/SessionPage.tsx",
  ])("%s 表单弹层传 maskClosable={false}", (rel) => {
    expect(read(rel)).toContain("maskClosable={false}")
  })

  /** 截取 src 中 from 到 to 之间的片段（即遮罩元素自身）；该片段不得再
      绑定关闭 —— 内层「取消」按钮的 onClick 是显式出口，不在截取范围。 */
  const region = (src: string, from: string, to: string) => {
    const start = src.indexOf(from)
    const end = src.indexOf(to, start)
    if (start < 0 || end < 0) throw new Error(`marker missing: ${from} -> ${to}`)
    return src.slice(start, end)
  }

  test("手写表单遮罩不再绑定关闭（Sidebar 新建项目 / Security 重验 / Schedule 编辑器/确认框）", () => {
    const sidebar = read("features/console/Sidebar.tsx")
    const projectSlice = sidebar.slice(
      sidebar.indexOf("function CreateProjectModal"),
      sidebar.indexOf("function ProjectMenu"),
    )
    const projectBackdrop = region(projectSlice, 'role="presentation"', 'role="dialog"')
    expect(projectBackdrop).not.toMatch(/onClick|onMouseDown/)
    expect(projectSlice).toContain('document.addEventListener("keydown"')

    const reauth = read("features/settings/SecuritySection.tsx")
    const reauthSlice = reauth.slice(
      reauth.indexOf("function ReauthDialog"),
      reauth.indexOf("function TotpSetup"),
    )
    const reauthBackdrop = region(reauthSlice, "bg-black/40", "<form")
    expect(reauthBackdrop).not.toMatch(/onClick|onMouseDown/)
    expect(reauthSlice).toContain('document.addEventListener("keydown"')

    const schedules = read("features/schedule/SchedulesPage.tsx")
    const editor = schedules.slice(
      schedules.indexOf("function ScheduleEditor"),
      schedules.indexOf("function ScheduleDrawer"),
    )
    const editorBackdrop = region(editor, "bg-black/40", "max-h-[85vh]")
    expect(editorBackdrop).not.toMatch(/onClick|onMouseDown/)
    // Esc 出口必须挂 document 级 —— overlay onKeyDown 在遮罩被点过
    // （焦点回落 body）后失效。
    expect(editor).toContain('document.addEventListener("keydown"')

    const confirm = schedules.slice(
      schedules.indexOf("function ConfirmDialog"),
      schedules.indexOf("function ScheduleEditor"),
    )
    const confirmBackdrop = region(confirm, 'role="presentation"', 'role="alertdialog"')
    expect(confirmBackdrop).not.toMatch(/onClick|onMouseDown/)
  })

  test("SchedulesPage 本地确认框：alertdialog 且删除走 danger", () => {
    const src = read("features/schedule/SchedulesPage.tsx")
    const confirm = src.slice(src.indexOf("function ConfirmDialog"), src.indexOf("function ScheduleEditor"))
    expect(confirm).toContain('role="alertdialog"')
    expect(confirm).toContain('"bg-failure text-white"')
    expect(src).toContain("danger\n")
  })
})

describe("审批中立与验证码输入", () => {
  test("批准/拒绝同用次级 outline 按钮（不做视觉引导）", () => {
    const src = read("features/approvals/ApprovalItem.tsx")
    const buttons = src.slice(src.indexOf("decide"))
    expect((buttons.match(/variant="outline"/g) ?? []).length).toBeGreaterThanOrEqual(2)
    expect(buttons).not.toContain('variant="default"')
  })

  test.each([
    "features/auth/LoginPage.tsx",
    "features/auth/RegisterPage.tsx",
    "features/auth/ForgotPasswordPage.tsx",
    "features/settings/SecuritySection.tsx",
  ])("%s 验证码：inputMode=numeric + one-time-code", (rel) => {
    const src = read(rel)
    expect(src).toContain('inputMode="numeric"')
    expect(src).toContain('autoComplete="one-time-code"')
  })
})

describe("移动端抽屉与安全区", () => {
  test("SettingsShell 抽屉锁背景滚动并恢复 + 焦点还原", () => {
    const src = read("features/settings/SettingsShell.tsx")
    expect(src).toContain('document.body.style.overflow = "hidden"')
    expect(src).toContain("document.body.style.overflow = previousOverflow")
    expect(src).toContain("previous.focus")
  })

  test("feedback 底部全宽提示卡避开 Home Bar", () => {
    const css = read("features/feedback/feedback.css")
    expect(css).toContain("env(safe-area-inset-bottom)")
  })

  test("Toast 不压 Home Bar", () => {
    const src = read("features/console/ConsoleShell.tsx")
    expect(src).toContain("env(safe-area-inset-bottom)")
  })
})

describe("accent 令牌通道", () => {
  test("tailwind.config.js 注册 accent / accent-ink", () => {
    const cfg = readWeb("tailwind.config.js")
    expect(cfg).toContain('variableColor("accent")')
    expect(cfg).toContain('"accent-ink"')
  })

  test("globals.css 提供 --rxy-accent-rgb 默认通道", () => {
    expect(read("styles/globals.css")).toContain("--rxy-accent-rgb:")
  })

  test("外观引擎写入 accent 时同步 -rgb 通道（/30 透明度修饰可用）", () => {
    const src = read("lib/appearance.ts")
    expect(src).toContain("--rxy-accent-rgb")
    expect(src).toContain("hexToRgbChannels")
  })
})
