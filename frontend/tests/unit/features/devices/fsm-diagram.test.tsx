import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("mermaid", () => ({
    default: {
        initialize: vi.fn(),
        render: vi.fn(async () => ({
            svg: '<svg><g class="node"><text>OFF</text></g><g class="node"><text>ON</text></g></svg>',
        })),
    },
}));

import { FsmDiagram } from "@/features/devices/fsm-diagram";
import { resetIdentity } from "@/lib/api";

function mockFetch(diagram: { ok: boolean; body: string }) {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/api/v1/session")) {
            return new Response(
                JSON.stringify({ user_id: "admin_user", is_admin: true, display_name: "x" }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            );
        }
        return new Response(diagram.body, { status: diagram.ok ? 200 : 404 });
    });
}

describe("FsmDiagram", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetIdentity();
    });

    it("рисует схему и подсвечивает текущее состояние", async () => {
        mockFetch({ ok: true, body: "graph TD; A-->B" });
        render(<FsmDiagram entityId="light.girlianda" currentState="ON" />);

        await waitFor(() =>
            expect(screen.getByTestId("fsm-diagram").querySelector("svg")).toBeTruthy(),
        );
        await waitFor(() =>
            expect(screen.getByTestId("fsm-diagram").querySelectorAll(".fsm-current")).toHaveLength(
                1,
            ),
        );
        const current = screen.getByTestId("fsm-diagram").querySelectorAll(".fsm-current");
        expect(current[0]?.textContent).toBe("ON");
    });

    it("честно сообщает, что схема не построена", async () => {
        mockFetch({ ok: false, body: "nope" });
        render(<FsmDiagram entityId="sensor.x" />);

        await waitFor(() =>
            expect(screen.getByText(/Схема для этого устройства не построена/)).toBeInTheDocument(),
        );
    });
});
