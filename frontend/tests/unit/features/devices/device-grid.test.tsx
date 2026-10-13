import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
    default: ({ children, ...props }: { children: ReactNode }) => <a {...props}>{children}</a>,
}));

import { DeviceGrid } from "@/features/devices/device-grid";
import { resetIdentity } from "@/lib/api";
import type { Device } from "@/lib/types";

function device(overrides: Partial<Device> = {}): Device {
    return {
        id: overrides.id ?? "d1",
        name: overrides.name ?? "Свет",
        ha_entity_id: overrides.ha_entity_id ?? "light.svet",
        device_type: overrides.device_type ?? "light",
        status: overrides.status ?? "available",
        state: overrides.state ?? { state: "on" },
        location: null,
        room_id: overrides.room_id ?? "spalnia",
        room_name: overrides.room_name ?? "Спальня",
        fsm: overrides.fsm ?? [],
    };
}

const DEVICES: Device[] = [
    device({
        id: "d1",
        name: "Свет над столом",
        ha_entity_id: "light.stol",
        room_name: "Гостиная",
    }),
    device({
        id: "d2",
        name: "Гирлянда",
        ha_entity_id: "light.girlianda",
        room_name: "Терраса",
        status: "unavailable",
    }),
    device({
        id: "d3",
        name: "Обогреватель",
        ha_entity_id: "switch.obogrev",
        device_type: "switch",
        room_name: "Спальня",
        fsm: [
            {
                fsm_id: "switch.obogrev_climate_10",
                device_id: "switch.obogrev",
                behavior: "climate",
                state: "HEATING",
                since: null,
            },
        ],
    }),
];

function wrapper({ children }: { children: ReactNode }) {
    return (
        <QueryClientProvider
            client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
            {children}
        </QueryClientProvider>
    );
}

function mockFetch(overrides: unknown = []) {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        const body = url.includes("/api/v1/session")
            ? { user_id: "admin_user", is_admin: true, display_name: "x" }
            : overrides;
        return new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });
    });
}

describe("DeviceGrid", () => {
    beforeEach(() => {
        mockFetch();
    });
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает приборы с русским типом и состоянием автомата", () => {
        render(<DeviceGrid devices={DEVICES} />, { wrapper });

        expect(screen.getByText("Свет над столом")).toBeInTheDocument();
        expect(screen.getAllByText("Терраса").length).toBeGreaterThan(0);
        expect(screen.getAllByText("свет").length).toBeGreaterThan(0);
        expect(screen.getByText("climate")).toBeInTheDocument();
        expect(screen.getByText("греет")).toBeInTheDocument();
        expect(screen.getByText(/показано 3 из 3/)).toBeInTheDocument();
    });

    it("ищет по имени и сущности", async () => {
        render(<DeviceGrid devices={DEVICES} />, { wrapper });

        await userEvent.type(screen.getByPlaceholderText(/имя, сущность/i), "гирл");

        expect(screen.getByText("Гирлянда")).toBeInTheDocument();
        expect(screen.queryByText("Свет над столом")).not.toBeInTheDocument();
        expect(screen.getByText(/показано 1 из 3/)).toBeInTheDocument();
    });

    it("фильтрует по комнате", async () => {
        render(<DeviceGrid devices={DEVICES} />, { wrapper });

        await userEvent.selectOptions(screen.getByLabelText("Комната"), "Спальня");

        expect(screen.getByText("Обогреватель")).toBeInTheDocument();
        expect(screen.queryByText("Гирлянда")).not.toBeInTheDocument();
    });

    it("фильтрует недоступные приборы иконкой связи", async () => {
        render(<DeviceGrid devices={DEVICES} />, { wrapper });

        await userEvent.selectOptions(screen.getByLabelText("Доступность"), "unavailable");

        expect(screen.getByText("Гирлянда")).toBeInTheDocument();
        expect(screen.queryByText("Обогреватель")).not.toBeInTheDocument();
        expect(screen.getByLabelText("недоступен")).toBeInTheDocument();
    });

    it("группирует по комнате и показывает заголовки групп", () => {
        render(<DeviceGrid devices={DEVICES} />, { wrapper });

        expect(screen.getByText(/Гостиная · 1/)).toBeInTheDocument();
        expect(screen.getByText(/Терраса · 1/)).toBeInTheDocument();
    });

    it("сортирует по имени в обе стороны", async () => {
        render(<DeviceGrid devices={DEVICES} />, { wrapper });
        await userEvent.selectOptions(screen.getByLabelText("Группировка"), "none");
        const header = screen.getByRole("button", { name: /Прибор/ });

        await userEvent.click(header);
        let rows = screen.getAllByRole("row").slice(1);
        expect(within(rows[0]).getByText("Свет над столом")).toBeInTheDocument();

        await userEvent.click(header);
        rows = screen.getAllByRole("row").slice(1);
        expect(within(rows[0]).getByText("Гирлянда")).toBeInTheDocument();
    });

    it("показывает блокировку и снимает её", async () => {
        const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
            const url = String(input);
            if (url.includes("/api/v1/session")) {
                return new Response(
                    JSON.stringify({ user_id: "a", is_admin: true, display_name: "x" }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                );
            }
            if ((init?.method ?? "GET") === "DELETE") {
                return new Response(JSON.stringify({ status: "success" }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                });
            }
            return new Response(
                JSON.stringify([
                    {
                        entity_id: "light.stol",
                        started_at: 0,
                        expires_at: Date.now() / 1000 + 3600,
                        reason: "manual",
                        user_id: "webui",
                    },
                ]),
                { status: 200, headers: { "Content-Type": "application/json" } },
            );
        });
        render(<DeviceGrid devices={DEVICES} />, { wrapper });

        const release = await screen.findByRole("button", { name: /Снять/ });
        await userEvent.click(release);

        await vi.waitFor(() =>
            expect(fetchMock.mock.calls.some((call) => call[1]?.method === "DELETE")).toBe(true),
        );
    });

    it("сообщает, когда фильтры ничего не нашли", async () => {
        render(<DeviceGrid devices={DEVICES} />, { wrapper });

        await userEvent.type(screen.getByPlaceholderText(/имя, сущность/i), "нет-такого");

        expect(screen.getByText(/Ничего не найдено/)).toBeInTheDocument();
    });
});
