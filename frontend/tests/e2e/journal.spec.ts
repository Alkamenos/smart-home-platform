import { expect, test } from "@playwright/test";

/**
 * E2E журнала и схемы автомата (спека 017, US4).
 *
 * Проверяется обещание: журнал — живая лента, а не список, который надо
 * обновлять руками; схема автомата показывает, где мы сейчас.
 */
test.describe("Журнал", () => {
    test("открывается и показывает ленту или честное «записей нет»", async ({ page }) => {
        await page.goto("/journal/");

        await expect(page.getByRole("heading", { name: "Журнал" })).toBeVisible();
        await expect(
            page.getByTestId("journal-list").or(page.getByText(/Записей нет/)),
        ).toBeVisible({ timeout: 10_000 });
    });

    test("фильтр по трассировке открывает цепочку", async ({ page }) => {
        await page.goto("/journal/");

        const traceButton = page.getByRole("button", { name: "трассировка" }).first();
        if ((await traceButton.count()) === 0) {
            test.skip(true, "в журнале нет записей с трассировкой");
        }

        await traceButton.click();

        await expect(page.getByTestId("trace-chain")).toBeVisible();
    });
});

test.describe("Схема автомата", () => {
    test("раскрывается на странице прибора", async ({ page }) => {
        await page.goto("/devices/");
        const deviceLinks = page.locator('a[href^="/device/"]');

        if ((await deviceLinks.count()) === 0) {
            test.skip(true, "в доме нет устройств");
        }

        await deviceLinks.first().click();
        await page.getByText("Схема автоматики").click();

        await expect(
            page.getByTestId("fsm-diagram").or(page.getByText(/Схема для этого/)),
        ).toBeVisible({ timeout: 10_000 });
    });
});
