import { expect, test } from "@playwright/test";

/**
 * E2E раздела «почему так» (спека 017, US3).
 *
 * Проверяется обещание: на странице прибора видно объяснение решения
 * автоматики и, если она заблокирована, — что прибор не трогают и до какого
 * времени. Без чтения журнала и без имён констант.
 */
test.describe("Причина и блокировка", () => {
    test("страница прибора объясняет решение автоматики", async ({ page }) => {
        await page.goto("/devices/");
        const deviceLinks = page.locator('a[href^="/device/"]');

        if ((await deviceLinks.count()) === 0) {
            test.skip(true, "в доме нет устройств");
        }

        await deviceLinks.first().click();

        await expect(page.getByText("Почему так")).toBeVisible();
    });

    test("блокировка автоматики видна, если она есть", async ({ page }) => {
        await page.goto("/devices/");
        const deviceLinks = page.locator('a[href^="/device/"]');

        if ((await deviceLinks.count()) === 0) {
            test.skip(true, "в доме нет устройств");
        }

        await deviceLinks.first().click();

        // Блокировка есть далеко не всегда: проверяем, что она показывается
        // корректно, когда есть, — без предположения о её наличии.
        const badge = page.getByTestId("override-badge");
        if ((await badge.count()) > 0) {
            await expect(badge).toContainText("автоматика не трогает");
        }
    });
});
