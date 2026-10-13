import { expect, test } from "@playwright/test";

/**
 * E2E раздела «Система» (спека 017, US6).
 *
 * Проверяется обещание: видно, готова ли платформа и что именно не в порядке —
 * а не «тихий» дом, за которым непонятно, произошло ли событие или сломалась
 * система.
 */
test.describe("Система", () => {
    test("показывает готовность и источники", async ({ page }) => {
        await page.goto("/system/");

        await expect(page.getByRole("heading", { name: "Система" })).toBeVisible();
        await expect(page.getByTestId("system-panel")).toBeVisible();
        await expect(page.getByText(/готова|не готова/)).toBeVisible({ timeout: 10_000 });
    });

    test("раздел достижим из навигации", async ({ page }) => {
        await page.goto("/");
        await page.getByRole("link", { name: "Система" }).click();

        await expect(page.getByRole("heading", { name: "Система" })).toBeVisible();
    });
});
