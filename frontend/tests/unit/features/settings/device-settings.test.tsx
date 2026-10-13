import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DeviceSettings } from "@/features/settings/device-settings";
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

const DEVICE = {
    id: "d1",
    name: "Гирлянда",
    ha_entity_id: "light.girlianda",
    device_type: "light",
    status: "available",
    state: { state: "on" },
    location: null,
    fsm: [],
};

function mockFetch() {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.includes("/api/v1/session")) {
            return new Response(
                JSON.stringify({ user_id: "admin_user", is_admin: true, display_name: "x" }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            );
        }
        if (url.includes("/behaviors") && method === "PUT") {
            return new Response(JSON.stringify({ device_id: "d1", behaviors: [] }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            });
        }
        if (url.endsWith("/access") && method === "POST") {
            return new Response(JSON.stringify({ id: "a1", user_id: "guest", role: "viewer" }), {
                status: 201,
                headers: { "Content-Type": "application/json" },
            });
        }
        if (url.includes("/access")) {
            return new Response(JSON.stringify([]), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            });
        }
        if (url.includes("/api/v1/devices/d1")) {
            return new Response(
                JSON.stringify({
                    behaviors: [{ template: "lighting", priority: 10, params: { lux: 20 } }],
                }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            );
        }
        return new Response(
            JSON.stringify({ generated_at: "", locations: [], devices: [DEVICE], alerts: [] }),
            { status: 200, headers: { "Content-Type": "application/json" } },
        );
    });
}

describe("DeviceSettings", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("загружает поведения выбранного устройства и сохраняет их", async () => {
        const fetchMock = mockFetch();
        render(<DeviceSettings />, { wrapper });

        await waitFor(() =>
            expect(screen.getByRole("option", { name: "Гирлянда" })).toBeInTheDocument(),
        );
        await userEvent.selectOptions(screen.getByLabelText("Устройство"), "d1");

        await waitFor(() => expect(screen.getByLabelText("Шаблон")).toHaveValue("lighting"));

        await userEvent.click(screen.getByRole("button", { name: "Сохранить поведения" }));

        await waitFor(() =>
            expect(fetchMock.mock.calls.some((call) => call[1]?.method === "PUT")).toBe(true),
        );
        expect(await screen.findByText("Поведения сохранены")).toBeInTheDocument();
    });

    it("назначает доступ к прибору", async () => {
        const fetchMock = mockFetch();
        render(<DeviceSettings />, { wrapper });

        await waitFor(() =>
            expect(screen.getByRole("option", { name: "Гирлянда" })).toBeInTheDocument(),
        );
        await userEvent.selectOptions(screen.getByLabelText("Устройство"), "d1");

        await waitFor(() => expect(screen.getByText("Права доступа")).toBeInTheDocument());
        await userEvent.type(screen.getByLabelText("Пользователь"), "guest");
        await userEvent.click(screen.getByRole("button", { name: "Назначить" }));

        await waitFor(() =>
            expect(
                fetchMock.mock.calls.some(
                    (call) => call[1]?.method === "POST" && String(call[0]).endsWith("/access"),
                ),
            ).toBe(true),
        );
    });
});
