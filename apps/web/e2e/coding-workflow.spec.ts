import { test, expect } from "@playwright/test"

/**
 * Cloud coding onboarding. This file is the page contract.
 * The locked proof is tests/web/w6/test_w6_c06_unit.py, which calls the
 * shipped login, import allowlist, pytest, and artifact download.
 * Playwright is not a dependency of apps/web, and playwright.config.ts
 * points testDir at tests/web/w3. Do not treat an unrun spec as a pass.
 */
test("cloud onboarding shows the github gate and the current target", async ({ page }) => {
  await page.goto("/onboarding")
  await page.getByRole("button", { name: "云端" }).click()
  await expect(page.locator("[data-journey]")).toHaveAttribute("data-permission", "")
  await expect(page.locator("[data-journey]")).toHaveAttribute("data-target", "cloud")
  await expect(page.locator("[data-journey]")).toHaveAttribute("data-status", "needs-github")
  await expect(page.getByRole("button", { name: "使用 GitHub" })).toBeVisible()
})

test("local onboarding grants full permission only after login", async ({ page }) => {
  await page.goto("/onboarding")
  await page.getByRole("button", { name: "本地" }).click()
  await expect(page.locator("[data-journey]")).toHaveAttribute("data-permission", "")
  await expect(page.locator("[data-journey]")).toHaveAttribute("data-target", "local")
  await expect(page.locator("[data-journey]")).toHaveAttribute("data-status", "needs-login")
  await page.locator('input[type="password"]').fill(process.env.RXY_LOCAL_SECRET ?? "")
  await page.getByRole("button", { name: "登录" }).click()
  await expect(page.locator("[data-journey]")).toHaveAttribute("data-permission", "full")
  await expect(page.locator("[data-journey]")).toHaveAttribute("data-target", "local")
  await expect(page.locator("[data-journey]")).toHaveAttribute("data-status", "ready")
})
