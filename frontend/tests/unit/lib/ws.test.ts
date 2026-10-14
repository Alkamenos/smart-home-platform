import { afterEach, describe, expect, it, vi } from "vitest";

import { EventStream } from "@/lib/ws";
import { resetIdentity } from "@/lib/api";

class FakeSocket {
    static instances: FakeSocket[] = [];
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    sent: string[] = [];
    closed = false;

    constructor(public url: string) {
        FakeSocket.instances.push(this);
    }

    send(data: string): void {
        this.sent.push(data);
    }

    close(): void {
        this.closed = true;
    }
}

describe("EventStream", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
        resetIdentity();
        FakeSocket.instances = [];
    });

    function stubFetch() {
        vi.spyOn(globalThis, "fetch").mockResolvedValue(
            new Response(
                JSON.stringify({ user_id: "admin_user", is_admin: true, display_name: "x" }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            ),
        );
    }

    it("после открытия авторизуется и подписывается на темы", async () => {
        vi.stubGlobal("WebSocket", FakeSocket);
        stubFetch();
        const stream = new EventStream();
        stream.start();

        const socket = FakeSocket.instances[0];
        socket.onopen?.();
        await vi.waitFor(() => expect(socket.sent.length).toBeGreaterThanOrEqual(2));

        const sent = socket.sent.map((raw) => JSON.parse(raw));
        expect(sent[0]).toMatchObject({ type: "auth", user_id: "admin_user" });
        expect(sent[1]).toMatchObject({ type: "subscribe", topics: ["locations", "devices"] });
        stream.stop();
    });

    it("доставляет сообщения подписчикам", () => {
        vi.stubGlobal("WebSocket", FakeSocket);
        stubFetch();
        const stream = new EventStream();
        const received: string[] = [];
        stream.onMessage((message) => received.push(message.type));
        stream.start();

        FakeSocket.instances[0].onmessage?.({
            data: JSON.stringify({ type: "state_change", entity_id: "sensor.t" }),
        });

        expect(received).toEqual(["state_change"]);
        stream.stop();
    });

    it("игнорирует неразбираемое сообщение", () => {
        vi.stubGlobal("WebSocket", FakeSocket);
        stubFetch();
        const stream = new EventStream();
        const listener = vi.fn();
        stream.onMessage(listener);
        stream.start();

        FakeSocket.instances[0].onmessage?.({ data: "не json" });

        expect(listener).not.toHaveBeenCalled();
        stream.stop();
    });

    it("после stop не переподключается", () => {
        vi.stubGlobal("WebSocket", FakeSocket);
        vi.useFakeTimers();
        stubFetch();
        const stream = new EventStream();
        stream.start();
        const first = FakeSocket.instances.length;

        stream.stop();
        FakeSocket.instances[0].onclose?.();
        vi.advanceTimersByTime(60_000);

        expect(FakeSocket.instances.length).toBe(first);
        vi.useRealTimers();
    });
});
