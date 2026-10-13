import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DeviceControls } from "@/features/devices/device-controls";
import { resetIdentity } from "@/lib/api";

function wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function mockFetch(commandResponse: { status: number; body: unknown }) {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/api/v1/session")) {
            return new Response(
                JSON.stringify({ user_id: "admin_user", is_admin: true, display_name: "x" }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            );
        }
        return new Response(JSON.stringify(commandResponse.body), {
            status: commandResponse.status,
            headers: { "Content-Type": "application/json" },
        });
    });
}

describe("DeviceControls", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает отклик автоматики после успешной команды", async () => {
        mockFetch({
            status: 200,
            body: { automation_synced: true, status: "success", device_id: "d1" },
        });
        render(<DeviceControls deviceId="d1" entityId="light.girlianda" isOn={false} />, {
            wrapper,
        });

        await userEvent.click(screen.getByRole("button", { name: "Включить" }));

        await waitFor(() => expect(screen.getByText("автоматика учла")).toBeInTheDocument());
    });

    it("показывает причину, когда команда не выполнена", async () => {
        mockFetch({ status: 502, body: { detail: "Команда не выполнена: прибор не ответил" } });
        render(<DeviceControls deviceId="d1" entityId="light.girlianda" isOn={true} />, {
            wrapper,
        });

        await userEvent.click(screen.getByRole("button", { name: "Выключить" }));

        await waitFor(() => expect(screen.getByText(/прибор не ответил/)).toBeInTheDocument());
    });

    it("не показывает управление для неуправляемого домена", () => {
        mockFetch({ status: 200, body: {} });
        render(<DeviceControls deviceId="d1" entityId="sensor.temperature" isOn={false} />, {
            wrapper,
        });

        expect(screen.queryByRole("button")).not.toBeInTheDocument();
    });
});
