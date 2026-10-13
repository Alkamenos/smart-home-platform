import { expect, test } from "@playwright/test";

/**
 * E2E надёжности диалогов (спека 017, US5, FR-006).
 *
 * Регресс прежнего дефекта: в старом интерфейсе модальные окна переставали
 * открываться. Здесь проверяется, что диалог открывается, закрывается по Esc и
 * снова открывается — то есть состояние не «залипает».
 */
test.describe("Диалоги настроек", () => {
    test("диалог источника открывается, закрывается и открывается снова", async ({ page }) => {
        await page.goto("/settings/sources/");

        const trigger = page.getByRole("button", { name: "Добавить источник" });
        await trigger.click();
        await expect(page.getByRole("dialog", { name: /Новый источник/ })).toBeVisible();

        await page.keyboard.press("Escape");
        await expect(page.getByRole("dialog", { name: /Новый источник/ })).toBeHidden();

        await trigger.click();
        await expect(page.getByRole("dialog", { name: /Новый источник/ })).toBeVisible();
    });

    test("хаб настроек ведёт в подразделы", async ({ page }) => {
        await page.goto("/settings/");

        for (const label of ["Источники", "Устройства", "Локации", "Манифест"]) {
            await expect(page.getByText(label, { exact: true })).toBeVisible();
        }
    });
});
