import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
    default: ({ children, ...props }: { children: ReactNode }) => <a {...props}>{children}</a>,
}));

import { SystemPanel } from "@/features/system/system-panel";
import { resetIdentity } from "@/lib/api";

function wrapper({ children }: { children: ReactNode }) {
    return (
        <QueryClientProvider
            client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
            {children}
        </QueryClientProvider>
    );
}

function json(body: unknown, status = 200) {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    });
}

function mockFetch(ready: boolean) {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/api/v1/session")) {
            return json({ user_id: "admin_user", is_admin: true, display_name: "x" });
        }
        if (url.endsWith("/ready")) {
            return json(
                {
                    ready,
                    failed: ready ? [] : ["ha_connection"],
                    checks: {
                        data_dir: { ok: true },
                        ha_connection: ready
                            ? { ok: true, detail: "соединение установлено" }
                            : { ok: false, detail: "нет соединения с Home Assistant" },
                    },
                },
                ready ? 200 : 503,
            );
        }
        if (url.endsWith("/health")) {
            return json({ status: "ok" });
        }
        if (url.includes("/metrics")) {
            return new Response("# HELP up up\nup 1\n", { status: 200 });
        }
        if (url.includes("/api/v1/devices/sources")) {
            return json([
                {
                    id: "s1",
                    name: "Home Assistant",
                    url: "http://h",
                    status: "connected",
                    last_sync: "2026-10-13T09:00:00",
                    last_error: null,
                    created_at: "",
                    updated_at: "",
                },
            ]);
        }
        if (url.includes("/api/v1/logs")) {
            return json({
                count: 1,
                logs: [{ timestamp: "2026-10-13T09:00:00Z", level: "ERROR", message: "Сбой" }],
            });
        }
        return json({});
    });
}

describe("SystemPanel", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает готовность, источники и логи", async () => {
        mockFetch(true);
        render(<SystemPanel />, { wrapper });

        await waitFor(() => expect(screen.getByText("готова")).toBeInTheDocument());
        expect(screen.getByText("Все проверки пройдены.")).toBeInTheDocument();
        expect(screen.getByText("Home Assistant")).toBeInTheDocument();
        expect(screen.getByText("Сбой")).toBeInTheDocument();
    });

    it("показывает причину неготовности, а не пустой экран", async () => {
        mockFetch(false);
        render(<SystemPanel />, { wrapper });

        await waitFor(() => expect(screen.getByText("не готова")).toBeInTheDocument());
        expect(screen.getByText(/связь с Home Assistant/)).toBeInTheDocument();
        expect(screen.getByText(/нет соединения с Home Assistant/)).toBeInTheDocument();
    });
});
