"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import type { JournalResponse } from "@/lib/types";

/**
 * Цепочка по трассировке: «событие → решение → команда → результат» (US4).
 *
 * Показывает записи одной трассировки в порядке времени — так видно, чем было
 * вызвано решение и чем оно закончилось, без ручного поиска.
 *
 * @param props Трассировка и закрытие панели.
 * @returns Панель цепочки.
 */
export function TraceChain({ traceId, onClose }: { traceId: string; onClose: () => void }) {
    const { data, isLoading } = useQuery({
        queryKey: ["trace", traceId],
        queryFn: () =>
            apiFetch<JournalResponse>(
                `/api/v1/events?trace=${encodeURIComponent(traceId)}&limit=200`,
            ),
        enabled: Boolean(traceId),
    });

    const steps = [...(data?.records ?? [])].reverse();

    return (
        <Card data-testid="trace-chain">
            <div className="mb-3 flex items-center justify-between gap-2">
                <CardTitle>Цепочка по трассировке</CardTitle>
                <Button size="sm" variant="ghost" onClick={onClose}>
                    Закрыть
                </Button>
            </div>
            <div className="text-muted mb-2 font-mono text-xs">{traceId}</div>
            {isLoading ? (
                <p className="text-muted text-sm">Загрузка…</p>
            ) : steps.length === 0 ? (
                <p className="text-muted text-sm">Записей по этой трассировке нет.</p>
            ) : (
                <ol className="space-y-1 text-sm">
                    {steps.map((record, index) => (
                        <li key={`${record.at}:${index}`} className="flex items-center gap-3">
                            <span className="text-muted w-20 shrink-0 font-mono text-xs">
                                {new Date(record.at).toLocaleTimeString("ru-RU")}
                            </span>
                            <Badge variant={record.kind === "transition" ? "info" : "neutral"}>
                                {record.title}
                            </Badge>
                            <span className="min-w-0 flex-1 truncate">{record.message}</span>
                        </li>
                    ))}
                </ol>
            )}
        </Card>
    );
}
