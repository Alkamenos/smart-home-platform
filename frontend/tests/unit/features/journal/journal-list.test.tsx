import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-virtual", () => ({
    useVirtualizer: ({ count }: { count: number }) => ({
        getTotalSize: () => count * 44,
        getVirtualItems: () =>
            Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 44 })),
        measureElement: () => {},
    }),
}));

import { JournalList } from "@/features/journal/journal-list";
import { resetIdentity } from "@/lib/api";
import type { JournalRecord } from "@/lib/types";

function record(overrides: Partial<JournalRecord> = {}): JournalRecord {
    return {
        at: "2026-10-13T09:00:00Z",
        at_ts: 1_700_000_000,
        kind: "event",
        entity_id: "light.girlianda",
        title: "state_change",
        message: "light.girlianda: off → on",
        trace_id: "trace-1",
        old_value: "off",
        value: "on",
        ...overrides,
    };
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

function mockFetch(devices: unknown[] = []) {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        const body = url.includes("/api/v1/session")
            ? { user_id: "admin_user", is_admin: true, display_name: "x" }
            : { generated_at: "", house_name: "Дом", locations: [], devices, alerts: [] };
        return new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });
    });
}

describe("JournalList", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает переход состояний с подсветкой значений", async () => {
        mockFetch();
        render(<JournalList records={[record()]} />, { wrapper });

        await waitFor(() => expect(screen.getByText("off")).toBeInTheDocument());
        expect(screen.getByText("on")).toBeInTheDocument();
        expect(screen.getByText("→")).toBeInTheDocument();
    });

    it("показывает человекочитаемое имя прибора, если оно известно", async () => {
        mockFetch([
            {
                id: "d1",
                name: "Гирлянда на террасе",
                ha_entity_id: "light.girlianda",
                device_type: "light",
                status: "available",
                state: {},
                location: null,
                room_id: null,
                room_name: null,
                fsm: [],
            },
        ]);
        render(<JournalList records={[record()]} />, { wrapper });

        await waitFor(() => expect(screen.getByText("Гирлянда на террасе")).toBeInTheDocument());
        expect(
            screen.getByTitle(/light\.girlianda — нажмите, чтобы скопировать/),
        ).toBeInTheDocument();
    });

    it("ведёт к трассировке по нажатию", async () => {
        mockFetch();
        const onPickTrace = vi.fn();
        render(<JournalList records={[record()]} onPickTrace={onPickTrace} />, { wrapper });

        await userEvent.click(await screen.findByRole("button", { name: "трассировка" }));

        expect(onPickTrace).toHaveBeenCalledWith("trace-1");
    });

    it("различает переход автомата и событие", async () => {
        mockFetch();
        render(
            <JournalList records={[record({ kind: "transition", title: "Переход автомата" })]} />,
            { wrapper },
        );

        await waitFor(() => expect(screen.getByText("автомат")).toBeInTheDocument());
    });
});
