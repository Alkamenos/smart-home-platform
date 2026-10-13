import { expect, test } from "@playwright/test";

/**
 * E2E управления прибором (спека 017, US2).
 *
 * Проверяется отклик интерфейса: у управляемого прибора есть кнопка, а после
 * нажатия появляется либо подтверждение, либо понятная причина — «нажал и
 * ничего не понятно» недопустимо.
 */
test.describe("Управление", () => {
    test("страница прибора показывает управление и автоматику", async ({ page }) => {
        await page.goto("/devices/");
        const deviceLinks = page.locator('a[href^="/device/"]');

        if ((await deviceLinks.count()) === 0) {
            test.skip(true, "в доме нет устройств");
        }

        await deviceLinks.first().click();

        await expect(page.getByText("Автоматика")).toBeVisible();
        await expect(page.getByRole("button", { name: /Включить|Выключить/ })).toBeVisible();
    });

    test("нажатие даёт отклик: подтверждение или причину", async ({ page }) => {
        await page.goto("/devices/");
        const deviceLinks = page.locator('a[href^="/device/"]');

        if ((await deviceLinks.count()) === 0) {
            test.skip(true, "в доме нет устройств");
        }

        await deviceLinks.first().click();
        const button = page.getByRole("button", { name: /Включить|Выключить/ });
        if ((await button.count()) === 0) {
            test.skip(true, "устройство не управляется включением/выключением");
        }

        await button.click();

        // Либо подтверждение автоматики/прямой команды, либо причина ошибки —
        // но не «ничего не произошло».
        await expect(
            page.getByText(/автоматика учла|команда напрямую|не выполнена/).first(),
        ).toBeVisible({ timeout: 10_000 });
    });
});
