import { identityHeaders } from "@/lib/api";

/**
 * Клиент канала живых изменений (спека 017, FR-012, R-05).
 *
 * Подключается к `/api/v1/ws/events`, авторизуется идентичностью сессии и
 * подписывается на темы. При обрыве переподключается с удвоением паузы и
 * повторяет авторизацию с подписками — иначе после короткого сбоя интерфейс
 * молча остался бы без обновлений.
 */

export interface StateChangeMessage {
    type: "state_change";
    entity_id: string;
    value: unknown;
    old_value: unknown;
    at: string;
}

export type StreamMessage = StateChangeMessage | { type: string; [key: string]: unknown };

type Listener = (message: StreamMessage) => void;

const RECONNECT_MIN_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

export class EventStream {
    private socket: WebSocket | null = null;
    private readonly listeners = new Set<Listener>();
    private readonly topics: string[];
    private reconnectDelay = RECONNECT_MIN_MS;
    private stopped = false;
    private timer: ReturnType<typeof setTimeout> | null = null;

    constructor(topics: string[] = ["locations", "devices"]) {
        this.topics = topics;
    }

    /**
     * Подписаться на сообщения канала.
     *
     * @param listener Обработчик сообщения.
     * @returns Функция отписки.
     */
    onMessage(listener: Listener): () => void {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    /** Открыть соединение. */
    start(): void {
        this.stopped = false;
        this.connect();
    }

    /** Закрыть соединение и прекратить переподключения. */
    stop(): void {
        this.stopped = true;
        if (this.timer) {
            clearTimeout(this.timer);
            this.timer = null;
        }
        this.socket?.close(1000, "client stop");
        this.socket = null;
    }

    private connect(): void {
        if (typeof window === "undefined") {
            return;
        }
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const socket = new WebSocket(`${protocol}//${window.location.host}/api/v1/ws/events`);
        this.socket = socket;

        socket.onopen = async () => {
            this.reconnectDelay = RECONNECT_MIN_MS;
            const headers = await identityHeaders();
            socket.send(JSON.stringify({ type: "auth", user_id: headers["X-User-ID"] }));
            socket.send(JSON.stringify({ type: "subscribe", topics: this.topics }));
        };

        socket.onmessage = (event) => {
            let message: StreamMessage;
            try {
                message = JSON.parse(event.data) as StreamMessage;
            } catch {
                return;
            }
            this.listeners.forEach((listener) => listener(message));
        };

        socket.onclose = () => {
            if (this.stopped) {
                return;
            }
            this.timer = setTimeout(() => {
                this.reconnectDelay = Math.min(this.reconnectDelay * 2, RECONNECT_MAX_MS);
                this.connect();
            }, this.reconnectDelay);
        };

        socket.onerror = () => socket.close();
    }
}
