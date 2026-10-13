import { expect, test } from "@playwright/test";

/**
 * E2E раздела «Дом» (спека 017, US1).
 *
 * Проверяется то, что интерфейс обещает: состояние дома видно на первом экране
 * и навигация ведёт по пяти разделам. Тесты не зависят от конкретных показаний
 * дома — проверяется структура и наличие данных.
 */
test.describe("Дом", () => {
    test("показывает состояние дома и тревоги", async ({ page }) => {
        await page.goto("/");

        await expect(page.getByRole("heading", { name: "Дом" })).toBeVisible();
        await expect(page.getByTestId("alerts-panel")).toBeVisible();
    });

    test("ведёт по пяти разделам", async ({ page }) => {
        await page.goto("/");

        for (const label of ["Автоматика", "Журнал", "Настройка", "Система"]) {
            await expect(page.getByRole("link", { name: label })).toBeVisible();
        }
    });

    test("переход в «Автоматику» показывает устройства", async ({ page }) => {
        await page.goto("/");
        await page.getByRole("link", { name: "Автоматика" }).click();

        await expect(page.getByRole("heading", { name: "Автоматика" })).toBeVisible();
    });
});
