import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch, ingressPrefix, resetIdentity, withIngress } from "@/lib/api";

/**
 * Запросы интерфейса под ingress Home Assistant (B79).
 *
 * Аддон живёт по пути `/api/hassio_ingress/<token>/`: без префикса запросы
 * `/api/...` уходят в корень домена, то есть в сам Home Assistant. Сервер
 * подставляет префикс в HTML (`window.__INGRESS_PATH__`), а клиент дописывает
 * его к запросам API и WebSocket.
 */
describe("ingress-префикс в клиенте API", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
        delete window.__INGRESS_PATH__;
    });

    it("дописывает префикс к сессии и запросам API", async () => {
        window.__INGRESS_PATH__ = "/api/hassio_ingress/token";
        const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
            async () =>
                new Response(JSON.stringify({ ok: true }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
        );

        await apiFetch("/api/v1/locations");

        const urls = fetchMock.mock.calls.map((call) => String(call[0]));
        expect(urls).toContain("/api/hassio_ingress/token/api/v1/session");
        expect(urls).toContain("/api/hassio_ingress/token/api/v1/locations");
    });

    it("без префикса пути остаются прежними", async () => {
        const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
            async () =>
                new Response(JSON.stringify({ ok: true }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
        );

        await apiFetch("/api/v1/locations");

        const urls = fetchMock.mock.calls.map((call) => String(call[0]));
        expect(urls).toContain("/api/v1/locations");
    });

    it("не трогает внешние адреса", () => {
        window.__INGRESS_PATH__ = "/api/hassio_ingress/token";

        expect(withIngress("https://example.com/x")).toBe("https://example.com/x");
        expect(ingressPrefix()).toBe("/api/hassio_ingress/token");
    });

    it("снимает хвостовой слэш у префикса", () => {
        window.__INGRESS_PATH__ = "/api/hassio_ingress/token/";

        expect(ingressPrefix()).toBe("/api/hassio_ingress/token");
    });
});
