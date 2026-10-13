import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

let captured: ((message: { type: string }) => void) | null = null;
const startSpy = vi.fn();
const stopSpy = vi.fn();

vi.mock("@/lib/ws", () => ({
    EventStream: class {
        onMessage(listener: (message: { type: string }) => void) {
            captured = listener;
            return () => {};
        }
        start() {
            startSpy();
        }
        stop() {
            stopSpy();
        }
    },
}));

import { useLiveOverview } from "@/features/home/use-live-overview";

function makeWrapper(client: QueryClient) {
    return function Wrapper({ children }: { children: ReactNode }) {
        return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    };
}

describe("useLiveOverview", () => {
    afterEach(() => {
        vi.clearAllMocks();
        captured = null;
    });

    it("показывает подключение после авторизации", () => {
        const client = new QueryClient();
        const { result } = renderHook(() => useLiveOverview(), { wrapper: makeWrapper(client) });

        expect(startSpy).toHaveBeenCalled();
        expect(result.current).toBe(false);

        act(() => captured?.({ type: "authenticated" }));

        expect(result.current).toBe(true);
    });

    it("обновляет агрегат при изменении состояния", () => {
        const client = new QueryClient();
        const invalidate = vi.spyOn(client, "invalidateQueries");
        renderHook(() => useLiveOverview(), { wrapper: makeWrapper(client) });

        act(() => captured?.({ type: "state_change" }));

        expect(invalidate).toHaveBeenCalledWith({ queryKey: ["overview"] });
    });

    it("останавливает поток при размонтировании", () => {
        const client = new QueryClient();
        const { unmount } = renderHook(() => useLiveOverview(), { wrapper: makeWrapper(client) });

        unmount();

        expect(stopSpy).toHaveBeenCalled();
    });
});
