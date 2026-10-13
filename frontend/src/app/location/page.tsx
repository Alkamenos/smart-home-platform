"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Sparkline } from "@/components/ui/sparkline";
import { apiFetch, ApiError } from "@/lib/api";
import { kindLabel, readingValue, roleLabel } from "@/lib/labels";
import { clockTime, relativeTime } from "@/lib/time";
import type { LocationSnapshot, Reading } from "@/lib/types";

interface HistoryResponse {
    location_id: string;
    count: number;
    records: Array<{
        at: string;
        entity_id: string;
        role: string | null;
        old_value: unknown;
        value: unknown;
    }>;
}

/**
 * Внутреннее представление страницы локации: графики, снимок и история гридами.
 *
 * @returns Страница локации.
 */
function LocationView() {
    const params = useSearchParams();
    const id = params.get("id") ?? "";

    const snapshot = useQuery({
        queryKey: ["location", id],
        queryFn: () =>
            apiFetch<LocationSnapshot>(`/api/v1/locations/${encodeURIComponent(id)}/state`),
        enabled: Boolean(id),
    });
    const history = useQuery({
        queryKey: ["locationHistory", id],
        queryFn: () =>
            apiFetch<HistoryResponse>(`/api/v1/locations/${encodeURIComponent(id)}/history`),
        enabled: Boolean(id),
    });

    if (!id) {
        return <Card>Не указана локация.</Card>;
    }
    if (snapshot.isLoading) {
        return <Skeleton className="h-48" />;
    }
    if (snapshot.error || !snapshot.data) {
        return (
            <Card>
                <CardTitle>Не удалось открыть локацию</CardTitle>
                <p className="text-muted mt-2 text-sm">
                    {snapshot.error instanceof ApiError
                        ? snapshot.error.message
                        : "Локация недоступна"}
                </p>
            </Card>
        );
    }

    const data = snapshot.data;
    const series = data.series ?? {};
    const rows: Array<{ role: string; reading: Reading }> = Object.entries(
        data.readings ?? {},
    ).flatMap(([role, items]) => items.map((reading) => ({ role, reading })));

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between gap-3">
                <h1 className="flex min-w-0 items-baseline gap-2 text-xl font-semibold">
                    <span className="truncate">{data.location.name}</span>
                    <span className="text-muted text-xs">{kindLabel(data.location.kind)}</span>
                </h1>
                <Link href="/" className="text-accent shrink-0 text-xs hover:underline">
                    ← Дом
                </Link>
            </div>

            {Object.keys(series).length > 0 ? (
                <Card>
                    <CardTitle>История</CardTitle>
                    <div className="mt-2 flex flex-wrap gap-6">
                        {Object.entries(series).map(([role, points]) => (
                            <div key={role}>
                                <div className="text-muted mb-1 text-xs">{roleLabel(role)}</div>
                                <Sparkline points={points} />
                            </div>
                        ))}
                    </div>
                </Card>
            ) : null}

            <Card>
                <CardTitle>Показания</CardTitle>
                <div className="border-border mt-2 overflow-x-auto rounded-lg border">
                    <table className="w-full border-collapse text-sm">
                        <thead className="bg-surface-2 text-left">
                            <tr>
                                <th className="border-border border-b px-3 py-2 text-xs font-semibold">
                                    Роль
                                </th>
                                <th className="border-border border-b px-3 py-2 text-xs font-semibold">
                                    Значение
                                </th>
                                <th className="border-border border-b px-3 py-2 text-xs font-semibold">
                                    Состояние
                                </th>
                                <th className="border-border border-b px-3 py-2 text-xs font-semibold">
                                    Обновлено
                                </th>
                                <th className="border-border border-b px-3 py-2 text-xs font-semibold">
                                    Сущность
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map(({ role, reading }) => (
                                <tr
                                    key={`${role}:${reading.entity_id}`}
                                    className="border-border border-b last:border-0"
                                >
                                    <td className="px-3 py-2 whitespace-nowrap">
                                        {roleLabel(role)}
                                    </td>
                                    <td className="px-3 py-2 font-mono whitespace-nowrap">
                                        {reading.available
                                            ? readingValue(reading.value, reading.unit)
                                            : "—"}
                                    </td>
                                    <td className="px-3 py-2">
                                        {!reading.available ? (
                                            <Badge variant="warning">недоступен</Badge>
                                        ) : reading.stale ? (
                                            <Badge variant="neutral">молчит</Badge>
                                        ) : (
                                            <Badge variant="success">есть</Badge>
                                        )}
                                    </td>
                                    <td className="text-muted px-3 py-2 whitespace-nowrap">
                                        {clockTime(reading.at)} · {relativeTime(reading.at)}
                                    </td>
                                    <td className="text-muted px-3 py-2 font-mono text-xs">
                                        {reading.entity_id}
                                    </td>
                                </tr>
                            ))}
                            {rows.length === 0 ? (
                                <tr>
                                    <td colSpan={5} className="text-muted px-3 py-6 text-center">
                                        Данных нет: у локации не заданы датчики или показаний ещё не
                                        было.
                                    </td>
                                </tr>
                            ) : null}
                        </tbody>
                    </table>
                </div>
            </Card>

            <Card>
                <CardTitle>История за сутки</CardTitle>
                <div className="border-border mt-2 max-h-96 overflow-auto rounded-lg border">
                    <table className="w-full border-collapse text-sm">
                        <thead className="bg-surface-2 sticky top-0 text-left">
                            <tr>
                                <th className="border-border border-b px-3 py-2 text-xs font-semibold">
                                    Время
                                </th>
                                <th className="border-border border-b px-3 py-2 text-xs font-semibold">
                                    Роль
                                </th>
                                <th className="border-border border-b px-3 py-2 text-xs font-semibold">
                                    Изменение
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {(history.data?.records ?? []).map((record, index) => (
                                <tr
                                    key={`${record.at}:${record.entity_id}:${index}`}
                                    className="border-border border-b last:border-0"
                                >
                                    <td className="text-muted px-3 py-2 whitespace-nowrap">
                                        {clockTime(record.at)}
                                    </td>
                                    <td className="px-3 py-2 whitespace-nowrap">
                                        {record.role ? roleLabel(record.role) : record.entity_id}
                                    </td>
                                    <td className="px-3 py-2 font-mono whitespace-nowrap">
                                        <span className="text-muted">
                                            {String(record.old_value ?? "—")}
                                        </span>
                                        <span className="text-muted"> → </span>
                                        <span>{String(record.value ?? "—")}</span>
                                    </td>
                                </tr>
                            ))}
                            {(history.data?.records ?? []).length === 0 ? (
                                <tr>
                                    <td colSpan={3} className="text-muted px-3 py-6 text-center">
                                        Изменений за сутки не было.
                                    </td>
                                </tr>
                            ) : null}
                        </tbody>
                    </table>
                </div>
            </Card>
        </div>
    );
}

/**
 * Обёртка с Suspense для чтения параметров запроса.
 *
 * @returns Страница локации.
 */
export default function LocationPage() {
    return (
        <Suspense fallback={<Skeleton className="h-48" />}>
            <LocationView />
        </Suspense>
    );
}
