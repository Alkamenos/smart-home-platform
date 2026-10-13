import { defineConfig, devices } from "@playwright/test";

/**
 * E2E проверяют собранный статический интерфейс, который раздаёт платформа.
 *
 * Адрес платформы задаётся переменной E2E_BASE_URL (по умолчанию локальный
 * запуск из `make run-webui`). Веб-сервер не поднимается автоматически: сначала
 * нужен `make frontend-build` и запущенная платформа.
 */
export default defineConfig({
    testDir: "./tests/e2e",
    fullyParallel: true,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 2 : 0,
    reporter: process.env.CI ? "github" : "list",
    use: {
        baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8000",
        trace: "on-first-retry",
    },
    projects: [
        { name: "chromium", use: { ...devices["Desktop Chrome"] } },
        { name: "mobile", use: { ...devices["Pixel 7"] } },
    ],
});
