import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-virtual", () => ({
    useVirtualizer: ({ count }: { count: number }) => ({
        getTotalSize: () => count * 52,
        getVirtualItems: () =>
            Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 52 })),
        measureElement: () => {},
    }),
}));

import JournalPage from "@/app/journal/page";
import { resetIdentity } from "@/lib/api";

const RESPONSE = {
    count: 1,
    next_cursor: null,
    records: [
        {
            at: "2026-10-13T09:00:00Z",
            at_ts: 1_700_000_000,
            kind: "event",
            entity_id: "sensor.t_spalnia",
            title: "state_change",
            message: "sensor.t_spalnia: 21.0 → 22.4",
            trace_id: "trace-1",
            old_value: "21.0",
            value: "22.4",
        },
    ],
};

function wrapper({ children }: { children: ReactNode }) {
    return (
        <QueryClientProvider
            client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
            {children}
        </QueryClientProvider>
    );
}

function mockFetch() {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        const body = url.includes("/api/v1/session")
            ? { user_id: "admin_user", is_admin: true, display_name: "x" }
            : RESPONSE;
        return new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });
    });
}

describe("JournalPage", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает живую ленту", async () => {
        mockFetch();
        render(<JournalPage />, { wrapper });

        await waitFor(() => expect(screen.getByTestId("journal-list")).toBeInTheDocument());
        expect(screen.getByText("21.0")).toBeInTheDocument();
        expect(screen.getByText("22.4")).toBeInTheDocument();
    });

    it("фильтрует ленту по сущности", async () => {
        const fetchMock = mockFetch();
        render(<JournalPage />, { wrapper });
        await waitFor(() => expect(screen.getByTestId("journal-list")).toBeInTheDocument());

        await userEvent.type(screen.getByPlaceholderText("light.girlianda"), "light.x");

        await waitFor(() => {
            const urls = fetchMock.mock.calls.map((call) => String(call[0]));
            expect(urls.some((url) => url.includes("entity=light.x"))).toBe(true);
        });
    });

    it("честно сообщает про пустую ленту", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
            const url = String(input);
            const body = url.includes("/api/v1/session")
                ? { user_id: "a", is_admin: true, display_name: "x" }
                : { count: 0, next_cursor: null, records: [] };
            return new Response(JSON.stringify(body), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            });
        });
        render(<JournalPage />, { wrapper });

        await waitFor(() => expect(screen.getByText(/Записей нет/)).toBeInTheDocument());
    });
});
