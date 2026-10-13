"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import { useState, type ReactNode } from "react";

import { createQueryClient } from "@/lib/query-client";

/**
 * Провайдеры интерфейса: кэш запросов и подсказки.
 *
 * @param props Дочерние элементы.
 * @returns Обёртка провайдеров.
 */
export function Providers({ children }: { children: ReactNode }) {
    const [queryClient] = useState<QueryClient>(() => createQueryClient());

    return (
        <QueryClientProvider client={queryClient}>
            <Tooltip.Provider delayDuration={200}>{children}</Tooltip.Provider>
        </QueryClientProvider>
    );
}
