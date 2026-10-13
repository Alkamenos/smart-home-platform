"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, identityHeaders, ApiError } from "@/lib/api";
import { clockTime } from "@/lib/time";
import type { PlatformLog, Readiness, ReadinessCheck, Source } from "@/lib/types";

/** Русские названия проверок готовности. */
const CHECK_LABELS: Record<string, string> = {
    data_dir: "каталог данных",
    encryption_key: "ключ шифрования",
    ha_connection: "связь с Home Assistant",
    watchdog: "снимки сторожа",
    engine: "движок автоматов",
    source_sync: "свежесть синхронизации источников",
};

/**
 * Назвать проверку готовности по-русски.
 *
 * @param name Ключ проверки.
 * @returns Человекочитаемое название.
 */
function checkLabel(name: string): string {
    return CHECK_LABELS[name] ?? name;
}

/**
 * Прочитать готовность: 503 тоже несёт тело с проверками.
 *
 * @returns Готовность платформы.
 */
async function fetchReadiness(): Promise<Readiness> {
    const response = await fetch("/ready", { headers: await identityHeaders() });
    const body = (await response.json()) as Readiness & { error?: string };
    if (response.status !== 200 && response.status !== 503) {
        throw new ApiError(response.status, body.error ?? "Не удалось получить готовность");
    }
    return body;
}

/**
 * Прочитать метрики: текстовый документ либо причина недоступности.
 *
 * @returns Текст метрик или причина.
 */
async function fetchMetrics(): Promise<{ text: string; reason?: string }> {
    const response = await fetch("/metrics", { headers: await identityHeaders() });
    if (response.status === 503 || response.status === 500) {
        const body = (await response.json().catch(() => ({}))) as { reason?: string };
        return { text: "", reason: body.reason ?? "Метрики недоступны" };
    }
    return { text: await response.text() };
}

/**
 * Раздел «Система»: готовность, источники, метрики и технические логи (US6).
 *
 * @returns Страница диагностики.
 */
export function SystemPanel() {
    const readiness = useQuery({ queryKey: ["readiness"], queryFn: fetchReadiness });
    const health = useQuery({
        queryKey: ["health"],
        queryFn: () => apiFetch<{ status: string }>("/health"),
    });
    const sources = useQuery({
        queryKey: ["sources"],
        queryFn: () => apiFetch<Source[]>("/api/v1/devices/sources"),
    });
    const metrics = useQuery({ queryKey: ["metrics"], queryFn: fetchMetrics });
    const logs = useQuery({
        queryKey: ["logs"],
        queryFn: () => apiFetch<{ count: number; logs: PlatformLog[] }>("/api/v1/logs"),
    });

    return (
        <div className="space-y-4" data-testid="system-panel">
            <h1 className="text-xl font-semibold">Система</h1>

            <Card>
                <div className="mb-3 flex items-center justify-between">
                    <CardTitle>Готовность</CardTitle>
                    {readiness.isLoading ? (
                        <Skeleton className="h-5 w-24" />
                    ) : readiness.data ? (
                        <Badge variant={readiness.data.ready ? "success" : "warning"}>
                            {readiness.data.ready ? "готова" : "не готова"}
                        </Badge>
                    ) : null}
                </div>

                {readiness.error ? (
                    <p className="text-muted text-sm">
                        {readiness.error instanceof ApiError
                            ? readiness.error.message
                            : "Готовность недоступна"}
                    </p>
                ) : null}

                {readiness.data ? (
                    readiness.data.ready ? (
                        <p className="text-muted text-sm">Все проверки пройдены.</p>
                    ) : (
                        <ul className="space-y-1 text-sm">
                            {Object.entries(readiness.data.checks)
                                .filter(([, check]) => !(check as ReadinessCheck).ok)
                                .map(([name, check]) => (
                                    <li key={name} className="flex items-start gap-2">
                                        <Badge variant="warning">не пройдена</Badge>
                                        <span className="min-w-0 break-words">
                                            {checkLabel(name)}
                                            {check.detail ? (
                                                <span className="text-muted">
                                                    {" "}
                                                    — {check.detail}
                                                </span>
                                            ) : null}
                                        </span>
                                    </li>
                                ))}
                        </ul>
                    )
                ) : null}
            </Card>

            <Card>
                <CardTitle>Процесс</CardTitle>
                <p className="text-muted mt-2 text-sm">
                    {health.data?.status === "ok"
                        ? "платформа отвечает"
                        : health.isLoading
                          ? "проверяю…"
                          : "нет ответа"}
                </p>
            </Card>

            <Card>
                <CardTitle>Источники</CardTitle>
                {(sources.data ?? []).length === 0 ? (
                    <p className="text-muted mt-2 text-sm">Источников нет.</p>
                ) : (
                    <ul className="mt-2 space-y-1 text-sm">
                        {(sources.data ?? []).map((source) => (
                            <li key={source.id} className="flex flex-wrap items-center gap-2">
                                <Badge
                                    variant={source.status === "connected" ? "success" : "warning"}
                                >
                                    {source.status === "connected" ? "подключён" : "нет связи"}
                                </Badge>
                                <span className="min-w-0 break-words">{source.name}</span>
                                {source.last_sync ? (
                                    <span className="text-muted min-w-0 break-words">
                                        синхронизация:{" "}
                                        {new Date(source.last_sync).toLocaleString("ru-RU")}
                                    </span>
                                ) : (
                                    <span className="text-muted">не синхронизирован</span>
                                )}
                            </li>
                        ))}
                    </ul>
                )}
                <Link
                    href="/settings/sources/"
                    className="text-accent mt-2 inline-block text-xs hover:underline"
                >
                    Настроить источники
                </Link>
            </Card>

            <Card>
                <CardTitle>Метрики</CardTitle>
                {metrics.data?.reason ? (
                    <p className="text-muted mt-2 text-sm">{metrics.data.reason}</p>
                ) : (
                    <details className="mt-2">
                        <summary className="cursor-pointer text-sm">
                            Показать документ метрик
                        </summary>
                        <pre className="border-border bg-surface-2 mt-2 max-h-72 overflow-auto rounded-md border p-3 text-xs">
                            {metrics.data?.text ?? ""}
                        </pre>
                    </details>
                )}
            </Card>

            <Card>
                <CardTitle>Технические логи</CardTitle>
                {logs.data && logs.data.logs.length > 0 ? (
                    <div className="border-border mt-2 max-h-72 overflow-auto rounded-lg border">
                        <table className="w-full border-collapse text-xs">
                            <thead className="bg-surface-2 sticky top-0 text-left">
                                <tr>
                                    <th className="border-border w-20 border-b px-3 py-1.5 font-semibold">
                                        Время
                                    </th>
                                    <th className="border-border w-20 border-b px-3 py-1.5 font-semibold">
                                        Уровень
                                    </th>
                                    <th className="border-border border-b px-3 py-1.5 font-semibold">
                                        Сообщение
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {logs.data.logs.map((entry, index) => (
                                    <tr
                                        key={`${entry.timestamp}:${index}`}
                                        className="border-border border-b last:border-0"
                                    >
                                        <td className="text-muted px-3 py-1.5 font-mono whitespace-nowrap">
                                            {clockTime(entry.timestamp)}
                                        </td>
                                        <td className="px-3 py-1.5">
                                            <Badge
                                                variant={
                                                    entry.level === "ERROR" ? "danger" : "neutral"
                                                }
                                            >
                                                {entry.level}
                                            </Badge>
                                        </td>
                                        <td className="px-3 py-1.5 break-words">{entry.message}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <p className="text-muted mt-2 text-sm">Сообщений пока нет.</p>
                )}
                <Link
                    href="/journal/"
                    className="text-accent mt-2 inline-block text-xs hover:underline"
                >
                    Журнал событий и переходов
                </Link>
            </Card>
        </div>
    );
}
