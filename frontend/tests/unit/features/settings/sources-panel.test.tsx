import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SourcesPanel } from "@/features/settings/sources-panel";
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

function mockFetch() {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.includes("/api/v1/session")) {
            return new Response(
                JSON.stringify({ user_id: "admin_user", is_admin: true, display_name: "x" }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            );
        }
        if (url.includes("/api/v1/devices/sources") && (init?.method ?? "GET") === "POST") {
            return new Response(JSON.stringify({ id: "s1", name: "HA" }), {
                status: 201,
                headers: { "Content-Type": "application/json" },
            });
        }
        return new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });
    });
}

describe("SourcesPanel", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("открывает диалог добавления источника (регресс модалок)", async () => {
        mockFetch();
        render(<SourcesPanel />, { wrapper });

        await userEvent.click(screen.getByRole("button", { name: "Добавить источник" }));

        await waitFor(() =>
            expect(screen.getByRole("dialog", { name: /Новый источник/ })).toBeInTheDocument(),
        );
    });

    it("показывает ошибки по полям, не отправляя пустую форму", async () => {
        const fetchMock = mockFetch();
        render(<SourcesPanel />, { wrapper });

        await userEvent.click(screen.getByRole("button", { name: "Добавить источник" }));
        await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));

        await waitFor(() => expect(screen.getByText("укажите название")).toBeInTheDocument());
        expect(screen.getByText("укажите адрес")).toBeInTheDocument();
        expect(fetchMock.mock.calls.some((call) => (call[1]?.method ?? "GET") === "POST")).toBe(
            false,
        );
    });

    it("сохраняет корректный источник", async () => {
        const fetchMock = mockFetch();
        render(<SourcesPanel />, { wrapper });

        await userEvent.click(screen.getByRole("button", { name: "Добавить источник" }));
        await userEvent.type(screen.getByLabelText("Название"), "HA");
        await userEvent.type(screen.getByLabelText("Адрес"), "http://192.168.1.10:8123");
        await userEvent.type(screen.getByLabelText("Токен"), "long-token-123");
        await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));

        await waitFor(() =>
            expect(fetchMock.mock.calls.some((call) => (call[1]?.method ?? "GET") === "POST")).toBe(
                true,
            ),
        );
    });

    it("импортирует выбранные сущности источника", async () => {
        const json = (body: unknown, status = 200) =>
            new Response(JSON.stringify(body), {
                status,
                headers: { "Content-Type": "application/json" },
            });
        const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
            const url = String(input);
            if (url.includes("/api/v1/session")) {
                return json({ user_id: "admin_user", is_admin: true, display_name: "x" });
            }
            if (url.includes("/discovery-data")) {
                return json({
                    source_id: "s1",
                    areas: [],
                    available_devices: [
                        {
                            entity_id: "light.x",
                            friendly_name: "Люстра",
                            device_type: "light",
                            area_id: null,
                            area_name: null,
                            state: "on",
                            icon: null,
                        },
                    ],
                    available_device_count: 1,
                    error: null,
                });
            }
            if (url.includes("/api/rooms")) {
                return json({ rooms: [{ id: "spalnia", name: "Спальня" }] });
            }
            if (url.includes("/api/v1/devices/apply")) {
                return json({ devices_added: 1, devices_updated: 0, failed: 0 }, 201);
            }
            if (url.includes("/api/v1/devices/sources")) {
                return json([
                    {
                        id: "s1",
                        name: "HA",
                        url: "http://h",
                        status: "connected",
                        last_sync: null,
                        last_error: null,
                        created_at: "",
                        updated_at: "",
                    },
                ]);
            }
            return json([]);
        });

        render(<SourcesPanel />, { wrapper });
        await waitFor(() => expect(screen.getByTestId("source-card")).toBeInTheDocument());

        await userEvent.click(screen.getByRole("button", { name: "Сущности" }));
        await waitFor(() => expect(screen.getByRole("checkbox")).toBeInTheDocument());

        await userEvent.click(screen.getByRole("checkbox"));
        await userEvent.click(screen.getByRole("button", { name: /Импортировать/ }));

        await waitFor(() =>
            expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/apply"))).toBe(
                true,
            ),
        );
    });
});
