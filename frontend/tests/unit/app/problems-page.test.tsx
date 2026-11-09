import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProblemsPage from "@/app/problems/page";
import { resetIdentity } from "@/lib/api";

const SNAPSHOT = {
    generated_at: "2026-11-09T12:00:00+05:00",
    count: 2,
    levels: { info: 0, warning: 1, critical: 1 },
    problems: [
        {
            id: "p1",
            subject: "sensor.spalnia_temperature",
            name: "Спальня температура",
            area: "Спальня",
            level: "warning",
            first_seen: "2026-11-09T10:00:00+05:00",
            last_seen: "2026-11-09T12:00:00+05:00",
            reasons: [
                {
                    id: "r1",
                    kind: "stale",
                    detail: "молчит 2.4 ч при ожидании 20 мин",
                    level: "warning",
                    first_seen: "2026-11-09T10:00:00+05:00",
                    last_seen: "2026-11-09T12:00:00+05:00",
                },
            ],
        },
        {
            id: "p2",
            subject: null,
            name: "Дом",
            area: "",
            level: "critical",
            first_seen: "2026-11-09T09:00:00+05:00",
            last_seen: "2026-11-09T12:00:00+05:00",
            reasons: [
                {
                    id: "r2",
                    kind: "house_unreadable",
                    detail: "состояния Home Assistant не прочитаны",
                    level: "critical",
                    first_seen: "2026-11-09T09:00:00+05:00",
                    last_seen: "2026-11-09T12:00:00+05:00",
                },
            ],
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

function mockFetch(snapshot: unknown = SNAPSHOT) {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        const body = url.includes("/api/v1/session")
            ? { user_id: "admin_user", is_admin: true, display_name: "x" }
            : snapshot;
        return new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });
    });
}

describe("ProblemsPage", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает проблемы и причины", async () => {
        mockFetch();
        render(<ProblemsPage />, { wrapper });

        await waitFor(() => expect(screen.getByText("Спальня температура")).toBeInTheDocument());
        expect(screen.getByText("молчит 2.4 ч при ожидании 20 мин")).toBeInTheDocument();
        expect(screen.getByText("КРИТИЧНО")).toBeInTheDocument();
    });

    it("фильтрует по уровню", async () => {
        mockFetch();
        render(<ProblemsPage />, { wrapper });
        await waitFor(() => expect(screen.getByText("Спальня температура")).toBeInTheDocument());

        await userEvent.click(screen.getByRole("button", { name: /Критичные/ }));

        expect(screen.getByText("Дом")).toBeInTheDocument();
        expect(screen.queryByText("Спальня температура")).not.toBeInTheDocument();
    });

    it("показывает явное «проблем нет»", async () => {
        mockFetch({
            generated_at: null,
            count: 0,
            levels: { info: 0, warning: 0, critical: 0 },
            problems: [],
        });
        render(<ProblemsPage />, { wrapper });

        await waitFor(() => expect(screen.getByText("Проблем нет.")).toBeInTheDocument());
    });
});
