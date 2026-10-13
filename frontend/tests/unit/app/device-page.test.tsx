import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
    useSearchParams: () => new URLSearchParams("id=d1"),
}));
vi.mock("next/link", () => ({
    default: ({ children, ...props }: { children: ReactNode }) => <a {...props}>{children}</a>,
}));
vi.mock("@/features/devices/fsm-diagram", () => ({
    FsmDiagram: () => <div data-testid="fsm-diagram" />,
}));

import DevicePage from "@/app/device/page";
import { resetIdentity } from "@/lib/api";

const DEVICE = {
    id: "d1",
    name: "Гирлянда",
    display_name: null,
    device_type: "light",
    status: "available",
    state: { state: "off" },
    ha_entity_id: "light.girlianda",
    ha_area_id: null,
    fsm: [
        {
            fsm_id: "light.girlianda_deco_light_20",
            device_id: "light.girlianda",
            behavior: "deco_light",
            state: "OFF",
            since: null,
        },
    ],
    behaviors: [{ template: "deco_light", priority: 20 }],
    automation: { configured: true, fsm_ids: ["x"], reason: null },
};

function mockFetch(body: unknown) {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/api/v1/session")) {
            return new Response(
                JSON.stringify({ user_id: "admin_user", is_admin: true, display_name: "x" }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            );
        }
        if (url.includes("/api/overrides")) {
            return new Response(JSON.stringify([]), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            });
        }
        return new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });
    });
}

function wrapper({ children }: { children: ReactNode }) {
    return (
        <QueryClientProvider
            client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
            {children}
        </QueryClientProvider>
    );
}

describe("DevicePage", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает прибор, автоматику и управление", async () => {
        mockFetch(DEVICE);
        render(<DevicePage />, { wrapper });

        await waitFor(() => expect(screen.getByText("Гирлянда")).toBeInTheDocument());
        expect(screen.getAllByText("deco_light").length).toBeGreaterThan(0);
        expect(screen.getByRole("button", { name: "Включить" })).toBeInTheDocument();
    });

    it("показывает причину, если устройство недоступно", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
            const url = String(input);
            if (url.includes("/api/v1/session")) {
                return new Response(
                    JSON.stringify({ user_id: "a", is_admin: true, display_name: "x" }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                );
            }
            if (url.includes("/api/overrides")) {
                return new Response(JSON.stringify([]), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                });
            }
            return new Response(JSON.stringify({ detail: "Устройство не найдено" }), {
                status: 404,
                headers: { "Content-Type": "application/json" },
            });
        });
        render(<DevicePage />, { wrapper });

        await waitFor(() => expect(screen.getByText("Устройство не найдено")).toBeInTheDocument());
    });
});
