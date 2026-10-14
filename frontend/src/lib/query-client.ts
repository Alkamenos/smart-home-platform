import { QueryClient } from "@tanstack/react-query";

/**
 * Кэш запросов интерфейса (спека 017, R-04).
 *
 * Настройки рассчитаны на живой пульт: данные не считаются вечно свежими, но и
 * не перезапрашиваются на каждое переключение раздела; живые обновления
 * приходят отдельным каналом и точечно обновляют кэш.
 *
 * @returns Настроенный клиент запросов.
 */
export function createQueryClient(): QueryClient {
    return new QueryClient({
        defaultOptions: {
            queries: {
                staleTime: 15_000,
                refetchOnWindowFocus: true,
                retry: 1,
            },
        },
    });
}
