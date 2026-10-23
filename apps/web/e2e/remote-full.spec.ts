import { test, expect } from "@playwright/test"

/**
 * Remote Full stays waiting until a local device confirms.
 * The shipped refusal is remote_full_unpaired in rxycode_server.release.journey.
 * An unpaired registry does not write remote-full.txt.
 * This spec only checks the page state. It does not grant a device.
 */
test("remote onboarding does not grant full execution", async ({ page }) => {
  await page.goto("/onboarding")
  await page.getByRole("button", { name: "远程" }).click()
  const journey = page.locator("[data-journey]")
  await expect(journey).toHaveAttribute("data-permission", "")
  await expect(journey).toHaveAttribute("data-target", "remote")
  await expect(journey).toHaveAttribute("data-status", "waiting_for_local_confirmation")
  await expect(page.getByRole("button", { name: "使用 GitHub" })).toHaveCount(0)
})
