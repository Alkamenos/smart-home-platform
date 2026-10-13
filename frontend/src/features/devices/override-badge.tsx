"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import type { Override } from "@/lib/types";

/**
 * Ручная блокировка автоматики со сроком (US3, FR-019).
 *
 * Показывает, что автоматика не трогает прибор, до какого времени, и позволяет
 * вернуть управление автоматике досрочно.
 *
 * @param props Сущность прибора.
 * @returns Бейдж блокировки либо ничего, если её нет.
 */
export function OverrideBadge({ entityId }: { entityId: string }) {
    const queryClient = useQueryClient();
    const { data, dataUpdatedAt } = useQuery({
        queryKey: ["overrides"],
        queryFn: () => apiFetch<Override[]>("/api/overrides"),
        refetchInterval: 30_000,
    });
    const release = useMutation({
        mutationFn: (id: string) =>
            apiFetch(`/api/override/${encodeURIComponent(id)}`, { method: "DELETE" }),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ["overrides"] }),
    });

    const active = data?.find((item) => item.entity_id === entityId);
    if (!active) {
        return null;
    }

    const until = new Date(active.expires_at * 1000);
    // Опорное время — момент загрузки данных (стабильно между рендерами):
    // вызов Date.now() прямо в рендере сделал бы результат нестабильным.
    const minutesLeft = Math.max(
        0,
        Math.round((active.expires_at * 1000 - dataUpdatedAt) / 60_000),
    );

    return (
        <div
            data-testid="override-badge"
            className="border-warning/40 bg-warning/10 flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm"
        >
            <Badge variant="warning">автоматика не трогает</Badge>
            <span className="text-muted">
                до {until.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })} (ещё
                ~{minutesLeft} мин)
            </span>
            <Button
                size="sm"
                variant="ghost"
                disabled={release.isPending}
                onClick={() => release.mutate(active.entity_id)}
            >
                Вернуть автоматику
            </Button>
        </div>
    );
}
