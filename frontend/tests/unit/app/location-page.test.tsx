import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
    useSearchParams: () => new URLSearchParams("id=spalnia"),
}));
vi.mock("next/link", () => ({
    default: ({ children, ...props }: { children: ReactNode }) => <a {...props}>{children}</a>,
}));

import LocationPage from "@/app/location/page";
import { resetIdentity } from "@/lib/api";

const SNAPSHOT = {
    location: { id: "spalnia", name: "Спальня", kind: "room" },
    at: "2026-10-13T09:00:00Z",
    available: true,
    readings: {
        temperature: [
            {
                value: "22.4",
                unit: "°C",
                at: "2026-10-13T09:00:00Z",
                stale: false,
                available: true,
                entity_id: "sensor.t_spalnia",
            },
        ],
    },
    derived: {},
    series: {
        temperature: [
            { at: "2026-10-13T08:00:00Z", value: 22.0 },
            { at: "2026-10-13T09:00:00Z", value: 22.4 },
        ],
    },
};

const HISTORY = {
    location_id: "spalnia",
    count: 1,
    records: [
        {
            at: "2026-10-13T08:00:00Z",
            entity_id: "sensor.t_spalnia",
            role: "temperature",
            old_value: "22.0",
            value: "22.4",
        },
    ],
};

function mockFetch() {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        let body: unknown = SNAPSHOT;
        if (url.includes("/api/v1/session")) {
            body = { user_id: "admin_user", is_admin: true, display_name: "x" };
        } else if (url.includes("/history")) {
            body = HISTORY;
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

describe("LocationPage", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает снимок и историю гридами", async () => {
        mockFetch();
        render(<LocationPage />, { wrapper });

        await waitFor(() => expect(screen.getByText("Спальня")).toBeInTheDocument());
        // Показания — грид: роль, значение, состояние, время, сущность.
        expect(screen.getByText("Показания")).toBeInTheDocument();
        expect(screen.getAllByText("температура").length).toBeGreaterThan(0);
        expect(screen.getByText("22.4 °C")).toBeInTheDocument();
        expect(screen.getByText("sensor.t_spalnia")).toBeInTheDocument();
        // История — грид.
        expect(screen.getByText("История за сутки")).toBeInTheDocument();
        expect(screen.getByText("22.0")).toBeInTheDocument();
    });

    it("показывает график истории, если он есть", async () => {
        mockFetch();
        render(<LocationPage />, { wrapper });

        await waitFor(() => expect(screen.getByText("История")).toBeInTheDocument());
        expect(screen.getByRole("img", { name: /История/ })).toBeInTheDocument();
    });
});
