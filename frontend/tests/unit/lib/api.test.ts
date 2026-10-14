import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch, ApiError, getIdentity, resetIdentity } from "@/lib/api";

describe("apiFetch", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("прикладывает заголовки идентичности к запросу", async () => {
        const fetchMock = vi
            .spyOn(globalThis, "fetch")
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({ user_id: "admin_user", is_admin: true, display_name: "x" }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ ok: true }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            );

        await getIdentity();
        await apiFetch("/api/v1/overview");

        const [, init] = fetchMock.mock.calls[1];
        const headers = new Headers(init?.headers);
        expect(headers.get("X-User-ID")).toBe("admin_user");
        expect(headers.get("X-Is-Admin")).toBe("true");
    });

    it("бросает ApiError с понятным сообщением", async () => {
        vi.spyOn(globalThis, "fetch")
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ user_id: "", is_admin: false, display_name: "" }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ error: "Движок не собран" }), {
                    status: 503,
                    headers: { "Content-Type": "application/json" },
                }),
            );

        const promise = apiFetch("/api/v1/overview");
        await expect(promise).rejects.toBeInstanceOf(ApiError);
        await expect(promise).rejects.toThrow("Движок не собран");
    });
});
