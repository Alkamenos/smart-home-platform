import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/settings/manifest-editor", () => ({
    // Редактор CodeMirror в jsdom не проверить; логика страницы (сохранение,
    // ошибки) тестируется через простую textarea с тем же контрактом.
    ManifestEditor: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => (
        <textarea
            aria-label="Манифест"
            value={value}
            onChange={(event) => onChange(event.target.value)}
        />
    ),
}));

import ManifestSettingsPage from "@/app/settings/manifest/page";
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

const MANIFEST = {
    manifest: {
        instance: { id: "probe", name: "Probe" },
        version: 1,
        rooms: [],
    },
    has_unsaved_changes: false,
};

function baseFetch() {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.includes("/api/v1/session")) {
            return new Response(
                JSON.stringify({ user_id: "admin_user", is_admin: true, display_name: "x" }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            );
        }
        if ((init?.method ?? "GET") === "PUT") {
            return new Response(
                JSON.stringify({
                    error: "Манифест не принят проверкой",
                    fields: [{ loc: "rooms.0.id", message: "обязательное поле" }],
                }),
                { status: 400, headers: { "Content-Type": "application/json" } },
            );
        }
        return new Response(JSON.stringify(MANIFEST), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });
    });
}

describe("ManifestSettingsPage", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("показывает текущий манифест", async () => {
        baseFetch();
        render(<ManifestSettingsPage />, { wrapper });

        await waitFor(() =>
            expect(screen.getByLabelText("Манифест")).toHaveValue(
                JSON.stringify(MANIFEST.manifest, null, 2),
            ),
        );
    });

    it("показывает ошибки по полям при отказе проверки", async () => {
        baseFetch();
        render(<ManifestSettingsPage />, { wrapper });
        await waitFor(() =>
            expect((screen.getByLabelText("Манифест") as HTMLTextAreaElement).value).not.toBe(""),
        );

        await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));

        await waitFor(() => expect(screen.getByTestId("manifest-errors")).toBeInTheDocument());
        expect(screen.getByText("rooms.0.id")).toBeInTheDocument();
        expect(screen.getByText(/обязательное поле/)).toBeInTheDocument();
    });

    it("честно говорит про некорректный JSON", async () => {
        baseFetch();
        render(<ManifestSettingsPage />, { wrapper });
        await waitFor(() =>
            expect((screen.getByLabelText("Манифест") as HTMLTextAreaElement).value).not.toBe(""),
        );

        const textarea = screen.getByLabelText("Манифест");
        await userEvent.clear(textarea);
        await userEvent.type(textarea, "{{ не json");
        await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));

        await waitFor(() =>
            expect(screen.getByText(/не является корректным JSON/)).toBeInTheDocument(),
        );
    });
});
