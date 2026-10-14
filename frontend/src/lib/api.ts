import type { Session } from "@/lib/types";

/**
 * Клиент API платформы (спека 017, R-03, R-04).
 *
 * Идентичность берётся один раз у `GET /api/v1/session` и прикладывается ко
 * всем запросам заголовками — модель доступа в локальной сети не меняется.
 * Ошибки платформы разбираются в понятное сообщение: пустота и ошибка не
 * смешиваются.
 */

export class ApiError extends Error {
    readonly status: number;

    constructor(status: number, message: string) {
        super(message);
        this.name = "ApiError";
        this.status = status;
    }
}

let identityPromise: Promise<Session> | null = null;

/** Сбросить кэш идентичности (для тестов). */
export function resetIdentity(): void {
    identityPromise = null;
}

/**
 * Идентичность текущей сессии (кэшируется на время жизни страницы).
 *
 * @returns Идентичность пользователя.
 */
export function getIdentity(): Promise<Session> {
    if (!identityPromise) {
        identityPromise = fetch("/api/v1/session")
            .then(async (response) => {
                if (!response.ok) {
                    return { user_id: "", is_admin: false, display_name: "" } satisfies Session;
                }
                return (await response.json()) as Session;
            })
            .catch(() => ({ user_id: "", is_admin: false, display_name: "" }) satisfies Session);
    }
    return identityPromise;
}

/**
 * Заголовки идентичности для запроса или WebSocket-авторизации.
 *
 * @returns Заголовки `X-User-ID` и `X-Is-Admin`.
 */
export async function identityHeaders(): Promise<Record<string, string>> {
    const identity = await getIdentity();
    return {
        "X-User-ID": identity.user_id,
        "X-Is-Admin": identity.is_admin ? "true" : "false",
    };
}

/**
 * Выполнить запрос к API с идентичностью и разбором ошибок.
 *
 * @param path Путь относительно того же origin (например, `/api/v1/overview`).
 * @param init Дополнительные параметры fetch.
 * @returns Разобранный JSON.
 * @throws ApiError если платформа ответила ошибкой.
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
    const headers = new Headers(init?.headers);
    if (!headers.has("Content-Type") && init?.body) {
        headers.set("Content-Type", "application/json");
    }
    for (const [key, value] of Object.entries(await identityHeaders())) {
        headers.set(key, value);
    }

    const response = await fetch(path, { ...init, headers });
    if (!response.ok) {
        throw new ApiError(response.status, await readError(response));
    }
    if (response.status === 204) {
        return undefined as T;
    }
    return (await response.json()) as T;
}

/**
 * Прочитать описание ошибки из ответа (JSON `detail`/`error` либо текст).
 *
 * @param response Ответ платформы.
 * @returns Понятное сообщение об ошибке.
 */
async function readError(response: Response): Promise<string> {
    try {
        const body = await response.json();
        return String(body.detail ?? body.error ?? `Ошибка ${response.status}`);
    } catch {
        return `Ошибка ${response.status}`;
    }
}
