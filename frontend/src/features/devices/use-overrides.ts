"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { Override } from "@/lib/types";

/**
 * Ручные блокировки автоматики (спека 017, US3, FR-019).
 *
 * Общий источник для грида «Автоматика» и страницы прибора: блокировка видна
 * там, где принимают решение, и её можно снять.
 *
 * @returns Список активных блокировок и функция снятия.
 */
export function useOverrides() {
    const queryClient = useQueryClient();
    const query = useQuery({
        queryKey: ["overrides"],
        queryFn: () => apiFetch<Override[]>("/api/overrides"),
        refetchInterval: 30_000,
    });
    const release = useMutation({
        mutationFn: (entityId: string) =>
            apiFetch(`/api/override/${encodeURIComponent(entityId)}`, { method: "DELETE" }),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ["overrides"] }),
    });
    return { overrides: query.data ?? [], release };
}
