import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/home/use-live-overview", () => ({ useLiveOverview: () => false }));
vi.mock("next/link", () => ({
    default: ({ children, ...props }: { children: ReactNode }) => <a {...props}>{children}</a>,
}));

import DevicesPage from "@/app/devices/page";
import { resetIdentity } from "@/lib/api";

const OVERVIEW = {
    generated_at: "2026-10-13T09:00:00Z",
    locations: [],
    devices: [
        {
            id: "d1",
            name: "Гирлянда",
            ha_entity_id: "light.girlianda",
            device_type: "light",
            status: "available",
            state: { state: "on" },
            location: null,
            fsm: [],
        },
    ],
    alerts: [],
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
        return new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });
    });
}

function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

describe("DevicesPage", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает устройства и ведёт на страницу прибора", async () => {
        mockFetch(OVERVIEW);
        render(<DevicesPage />, { wrapper });

        await waitFor(() => expect(screen.getByText("Гирлянда")).toBeInTheDocument());
        expect(screen.getByRole("link")).toHaveAttribute("href", "/device/?id=d1");
    });

    it("честно сообщает, что устройств нет", async () => {
        mockFetch({ ...OVERVIEW, devices: [] });
        render(<DevicesPage />, { wrapper });

        await waitFor(() => expect(screen.getByText(/Ничего не найдено/)).toBeInTheDocument());
    });
});
