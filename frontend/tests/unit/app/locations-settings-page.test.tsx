import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
    default: ({ children, ...props }: { children: ReactNode }) => <a {...props}>{children}</a>,
}));

import LocationsSettingsPage from "@/app/settings/locations/page";
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
        const payload = url.includes("/api/v1/session")
            ? { user_id: "admin_user", is_admin: true, display_name: "x" }
            : body;
        return new Response(JSON.stringify(payload), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });
    });
}

describe("LocationsSettingsPage", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает локации с числом датчиков и ведёт к снимку", async () => {
        mockFetch({
            locations: [
                {
                    id: "spalnia",
                    name: "Спальня",
                    kind: "room",
                    sensor_count: 2,
                    sensors: { temperature: "sensor.t_spalnia" },
                },
            ],
        });
        render(<LocationsSettingsPage />, { wrapper });

        await waitFor(() => expect(screen.getByText("Спальня")).toBeInTheDocument());
        expect(screen.getByText("комната")).toBeInTheDocument();
        expect(screen.getByText("2 датч.")).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Спальня" })).toHaveAttribute(
            "href",
            "/location/?id=spalnia",
        );
    });

    it("открывает правку ролей и сохраняет привязку", async () => {
        const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
            const url = String(input);
            if (url.includes("/api/v1/session")) {
                return new Response(
                    JSON.stringify({ user_id: "admin_user", is_admin: true, display_name: "x" }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                );
            }
            if ((init?.method ?? "GET") === "PUT") {
                return new Response(JSON.stringify({ status: "saved" }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                });
            }
            return new Response(
                JSON.stringify({
                    locations: [
                        {
                            id: "spalnia",
                            name: "Спальня",
                            kind: "room",
                            sensor_count: 1,
                            sensors: { temperature: "sensor.t_spalnia" },
                        },
                    ],
                }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            );
        });
        render(<LocationsSettingsPage />, { wrapper });

        await waitFor(() =>
            expect(screen.getByRole("button", { name: "Роли" })).toBeInTheDocument(),
        );
        await userEvent.click(screen.getByRole("button", { name: "Роли" }));
        await waitFor(() => expect(screen.getByLabelText("Роль")).toHaveValue("temperature"));

        await userEvent.click(screen.getByRole("button", { name: "Сохранить роли" }));

        await waitFor(() =>
            expect(fetchMock.mock.calls.some((call) => call[1]?.method === "PUT")).toBe(true),
        );
    });

    it("показывает причину, если локации недоступны", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
            const url = String(input);
            if (url.includes("/api/v1/session")) {
                return new Response(
                    JSON.stringify({ user_id: "a", is_admin: true, display_name: "x" }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                );
            }
            return new Response(JSON.stringify({ error: "Наблюдение не собрано" }), {
                status: 503,
                headers: { "Content-Type": "application/json" },
            });
        });
        render(<LocationsSettingsPage />, { wrapper });

        await waitFor(() => expect(screen.getByText("Наблюдение не собрано")).toBeInTheDocument());
    });
});
