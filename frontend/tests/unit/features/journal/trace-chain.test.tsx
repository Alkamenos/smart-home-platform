import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TraceChain } from "@/features/journal/trace-chain";
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

describe("TraceChain", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает записи трассировки в порядке времени", async () => {
        mockFetch({
            count: 2,
            next_cursor: null,
            records: [
                {
                    at: "2026-10-13T09:00:10Z",
                    at_ts: 2,
                    kind: "transition",
                    entity_id: "light.x_lighting_10",
                    title: "Переход автомата",
                    message: "light.x: OFF → ON (motion)",
                    trace_id: "t1",
                    old_value: null,
                    value: null,
                },
                {
                    at: "2026-10-13T09:00:00Z",
                    at_ts: 1,
                    kind: "event",
                    entity_id: "binary_sensor.m",
                    title: "state_change",
                    message: "binary_sensor.m: off → on",
                    trace_id: "t1",
                    old_value: null,
                    value: null,
                },
            ],
        });
        render(<TraceChain traceId="t1" onClose={() => {}} />, { wrapper });

        await waitFor(() =>
            expect(screen.getByText("binary_sensor.m: off → on")).toBeInTheDocument(),
        );
        const messages = screen.getAllByText(/→/).map((node) => node.textContent);
        expect(messages[0]).toContain("binary_sensor.m");
    });

    it("сообщает, если по трассировке записей нет", async () => {
        mockFetch({ count: 0, next_cursor: null, records: [] });
        render(<TraceChain traceId="t2" onClose={() => {}} />, { wrapper });

        await waitFor(() =>
            expect(screen.getByText(/Записей по этой трассировке нет/)).toBeInTheDocument(),
        );
    });
});
