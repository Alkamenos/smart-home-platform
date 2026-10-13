import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OverrideBadge } from "@/features/devices/override-badge";
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

function mockFetch(overrides: unknown, onDelete?: () => void) {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.includes("/api/v1/session")) {
            return new Response(
                JSON.stringify({ user_id: "admin_user", is_admin: true, display_name: "x" }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            );
        }
        if ((init?.method ?? "GET") === "DELETE") {
            onDelete?.();
            return new Response(JSON.stringify({ status: "success" }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            });
        }
        return new Response(JSON.stringify(overrides), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });
    });
}

describe("OverrideBadge", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает активную блокировку и позволяет вернуть автоматику", async () => {
        const onDelete = vi.fn();
        mockFetch(
            [
                {
                    entity_id: "light.girlianda",
                    started_at: Date.now() / 1000,
                    expires_at: Date.now() / 1000 + 3600,
                    reason: "Manual override",
                    user_id: "webui",
                },
            ],
            onDelete,
        );
        render(<OverrideBadge entityId="light.girlianda" />, { wrapper });

        await waitFor(() => expect(screen.getByText("автоматика не трогает")).toBeInTheDocument());
        await userEvent.click(screen.getByRole("button", { name: "Вернуть автоматику" }));

        await waitFor(() => expect(onDelete).toHaveBeenCalled());
    });

    it("ничего не показывает, если блокировки нет", async () => {
        mockFetch([]);
        render(<OverrideBadge entityId="light.girlianda" />, { wrapper });

        await waitFor(() => expect(screen.queryByTestId("override-badge")).not.toBeInTheDocument());
    });
});
