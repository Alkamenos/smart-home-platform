"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Card, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, ApiError } from "@/lib/api";
import type { JournalResponse } from "@/lib/types";

import { JournalList } from "@/features/journal/journal-list";
import { TraceChain } from "@/features/journal/trace-chain";

/**
 * Раздел «Журнал»: живая лента событий и переходов с фильтрами (US4).
 *
 * @returns Страница журнала.
 */
export default function JournalPage() {
    const [entity, setEntity] = useState("");
    const [trace, setTrace] = useState("");

    const params = new URLSearchParams({ limit: "200" });
    if (entity.trim()) {
        params.set("entity", entity.trim());
    }
    if (trace.trim()) {
        params.set("trace", trace.trim());
    }

    const { data, isLoading, error, dataUpdatedAt } = useQuery({
        queryKey: ["journal", entity.trim(), trace.trim()],
        queryFn: () => apiFetch<JournalResponse>(`/api/v1/events?${params.toString()}`),
        refetchInterval: 5_000,
    });

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h1 className="text-xl font-semibold">Журнал</h1>
                <span className="text-muted text-xs">
                    живой хвост · обновлено{" "}
                    {dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString("ru-RU") : "—"}
                </span>
            </div>

            <div className="flex flex-wrap gap-3">
                <label className="flex items-center gap-2 text-sm">
                    <span className="text-muted">Сущность</span>
                    <input
                        value={entity}
                        onChange={(event) => setEntity(event.target.value)}
                        placeholder="light.girlianda"
                        className="border-border bg-surface-2 rounded-md border px-2 py-1 font-mono text-xs"
                    />
                </label>
                <label className="flex items-center gap-2 text-sm">
                    <span className="text-muted">Трассировка</span>
                    <input
                        value={trace}
                        onChange={(event) => setTrace(event.target.value)}
                        placeholder="trace-id"
                        className="border-border bg-surface-2 rounded-md border px-2 py-1 font-mono text-xs"
                    />
                </label>
            </div>

            {trace.trim() ? (
                <TraceChain traceId={trace.trim()} onClose={() => setTrace("")} />
            ) : null}

            {isLoading ? <Skeleton className="h-[60vh]" /> : null}

            {error ? (
                <Card>
                    <CardTitle>Не удалось получить журнал</CardTitle>
                    <p className="text-muted mt-2 text-sm">
                        {error instanceof ApiError ? error.message : String(error)}
                    </p>
                </Card>
            ) : null}

            {data ? (
                data.records.length === 0 ? (
                    <Card>
                        <p className="text-muted text-sm">
                            Записей нет: либо фильтр слишком узкий, либо событий ещё не было.
                        </p>
                    </Card>
                ) : (
                    <JournalList records={data.records} onPickTrace={setTrace} />
                )
            ) : null}
        </div>
    );
}
