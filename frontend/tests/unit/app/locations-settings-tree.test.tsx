import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
    default: ({ children, ...props }: { children: ReactNode }) => <a {...props}>{children}</a>,
}));

import LocationsSettingsPage from "@/app/settings/locations/page";
import { resetIdentity } from "@/lib/api";

const PLACES = {
    locations: [
        {
            id: "ulitsa",
            name: "Улица",
            kind: "outdoor",
            sensor_count: 2,
            sensors: {},
            parent: null,
            devices: [],
        },
        {
            id: "sad",
            name: "Сад",
            kind: "garden",
            sensor_count: 1,
            sensors: {},
            parent: "ulitsa",
            devices: [
                {
                    id: "light.fonar",
                    name: "Фонарь",
                    type: "light",
                    behaviors: 0,
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

function mockFetch(onWrite?: (url: string, init?: RequestInit) => void) {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.includes("/api/v1/session")) {
            return new Response(
                JSON.stringify({ user_id: "admin_user", is_admin: true, display_name: "x" }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            );
        }
        const method = init?.method ?? "GET";
        if (method !== "GET") {
            onWrite?.(url, init);
            return new Response(JSON.stringify({ status: "saved" }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            });
        }
        return new Response(JSON.stringify(PLACES), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });
    });
}

describe("LocationsSettingsPage: дерево и перенос", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает место и его приборы", async () => {
        mockFetch();
        render(<LocationsSettingsPage />, { wrapper });

        await waitFor(() => expect(screen.getByText("Сад")).toBeInTheDocument());
        expect(screen.getByText("Улица")).toBeInTheDocument();
        expect(screen.getByText("Фонарь")).toBeInTheDocument();
        expect(screen.getByText("свет", { exact: false })).toBeInTheDocument();
    });

    it("переносит прибор в выбранное место", async () => {
        const writes: string[] = [];
        mockFetch((url) => writes.push(url));
        render(<LocationsSettingsPage />, { wrapper });

        await waitFor(() => expect(screen.getByText("Фонарь")).toBeInTheDocument());
        await userEvent.click(screen.getByRole("button", { name: "Переместить" }));

        const dialog = await screen.findByTestId("dialog-content");
        await userEvent.selectOptions(within(dialog).getByLabelText("Куда перенести"), "ulitsa");
        await userEvent.click(within(dialog).getByRole("button", { name: "Перенести" }));

        await waitFor(() => expect(writes.some((url) => url.includes("/devices"))).toBe(true));
    });

    it("создаёт новое место", async () => {
        const writes: { url: string; body?: string }[] = [];
        mockFetch((url, init) => writes.push({ url, body: String(init?.body ?? "") }));
        render(<LocationsSettingsPage />, { wrapper });

        await waitFor(() =>
            expect(screen.getByRole("button", { name: "Создать место" })).toBeInTheDocument(),
        );
        await userEvent.click(screen.getByRole("button", { name: "Создать место" }));

        const dialog = await screen.findByTestId("dialog-content");
        await userEvent.type(within(dialog).getByLabelText("Идентификатор"), "gazon");
        await userEvent.type(within(dialog).getByLabelText("Имя"), "Газон");
        await userEvent.click(within(dialog).getByRole("button", { name: "Создать место" }));

        await waitFor(() =>
            expect(writes.some((write) => write.url.endsWith("/api/v1/locations"))).toBe(true),
        );
        const created = writes.find((write) => write.url.endsWith("/api/v1/locations"));
        expect(created?.body).toContain("gazon");
    });
});
