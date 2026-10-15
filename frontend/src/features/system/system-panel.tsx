"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, identityHeaders, ApiError } from "@/lib/api";
import { clockTime } from "@/lib/time";
import type {
    CleanupHelper,
    CleanupReport,
    PlatformLog,
    Readiness,
    ReadinessCheck,
    Source,
} from "@/lib/types";

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
 * Назвать вердикт чистки по-русски.
 *
 * @param verdict Вердикт платформы.
 * @returns Человекочитаемое название.
 */
function verdictLabel(verdict: CleanupHelper["verdict"]): string {
    if (verdict === "probably_unused") {
        return "следов нет";
    }
    return verdict === "unknown" ? "не знаю" : "используется";
}

/**
 * Раздел «Система»: готовность, источники, метрики и технические логи (US6).
 *
 * @returns Страница диагностики.
 */
export function SystemPanel() {
    const [cleanupRound, setCleanupRound] = useState(0);
    const [copied, setCopied] = useState(false);
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
    const cleanup = useQuery({
        queryKey: ["cleanup", cleanupRound],
        queryFn: () =>
            apiFetch<CleanupReport>(
                `/api/v1/system/cleanup${cleanupRound > 0 ? "?refresh=true" : ""}`,
            ),
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

            <Card>
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <CardTitle>Чистка</CardTitle>
                    {cleanup.data ? (
                        <div className="flex items-center gap-3">
                            <Badge
                                variant={
                                    (cleanup.data?.counts?.probably_unused ?? 0) > 0
                                        ? "warning"
                                        : "success"
                                }
                            >
                                кандидатов: {cleanup.data?.counts?.probably_unused ?? 0}
                            </Badge>
                            <button
                                type="button"
                                className="text-accent text-xs hover:underline"
                                onClick={() => setCleanupRound((round) => round + 1)}
                            >
                                пересобрать
                            </button>
                        </div>
                    ) : null}
                </div>

                {cleanup.error ? (
                    <p className="text-muted text-sm">Список недоступен.</p>
                ) : cleanup.isLoading ? (
                    <Skeleton className="h-5 w-40" />
                ) : (cleanup.data?.helpers ?? []).length === 0 ? (
                    <p className="text-muted text-sm">Вспомогательных элементов не найдено.</p>
                ) : (
                    <>
                        <p className="text-muted mb-2 text-xs">
                            Платформа ничего не удаляет сама: список — это свидетельства.
                            Проверяются манифест дома, правила автоматизаций, панели и журнал
                            платформы. Удаление — правка YAML на самом доме: элементы, описанные в
                            YAML, живут не в нашей программе, а в конфигурации Home Assistant, и
                            дотянуться до неё платформа не может. Сцены и ручные вызовы скриптов она
                            тоже не видит — «следов нет» значит «здесь не нашлось», а не «точно
                            никому не нужно».
                            {cleanup.data?.sources?.automations === false
                                ? " Правила автоматизаций Home Assistant прочитать не удалось, поэтому вердикт «следов нет» не выносится."
                                : ""}
                        </p>
                        <div className="mb-2 flex flex-wrap items-center gap-3">
                            <button
                                type="button"
                                className="text-accent text-xs hover:underline"
                                onClick={() => {
                                    void navigator.clipboard
                                        ?.writeText(cleanup.data?.plan?.text ?? "")
                                        .then(() => setCopied(true));
                                }}
                            >
                                {copied
                                    ? "список скопирован"
                                    : "скопировать список для правки YAML"}
                            </button>
                            <span className="text-muted text-xs">
                                кандидатов по домам:{" "}
                                {Object.entries(cleanup.data?.plan?.by_domain ?? {})
                                    .map(([domain, list]) => `${domain} ${list.length}`)
                                    .join(", ")}
                            </span>
                        </div>
                        <div className="border-border max-h-80 overflow-auto rounded-lg border">
                            <table className="w-full border-collapse text-xs">
                                <thead className="bg-surface-2 sticky top-0 text-left">
                                    <tr>
                                        <th className="border-border border-b px-3 py-1.5 font-semibold">
                                            Элемент
                                        </th>
                                        <th className="border-border w-28 border-b px-3 py-1.5 font-semibold">
                                            Состояние
                                        </th>
                                        <th className="border-border w-24 border-b px-3 py-1.5 font-semibold">
                                            Откуда
                                        </th>
                                        <th className="border-border w-32 border-b px-3 py-1.5 font-semibold">
                                            Вердикт
                                        </th>
                                        <th className="border-border border-b px-3 py-1.5 font-semibold">
                                            Почему
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(cleanup.data?.helpers ?? []).map((helper) => (
                                        <tr
                                            key={helper.entity_id}
                                            className="border-border border-b last:border-0"
                                        >
                                            <td className="px-3 py-1.5">
                                                <span className="block">{helper.name}</span>
                                                <span className="text-muted block font-mono text-[11px]">
                                                    {helper.entity_id}
                                                </span>
                                            </td>
                                            <td className="text-muted px-3 py-1.5">
                                                {String(helper.state)}
                                            </td>
                                            <td
                                                className="text-muted px-3 py-1.5"
                                                title={helper.entity_id}
                                            >
                                                {helper.origin === "ui"
                                                    ? "через интерфейс"
                                                    : helper.origin === "yaml"
                                                      ? "описан в YAML"
                                                      : "неизвестно"}
                                            </td>
                                            <td className="px-3 py-1.5">
                                                <Badge
                                                    variant={
                                                        helper.verdict === "probably_unused"
                                                            ? "warning"
                                                            : "neutral"
                                                    }
                                                >
                                                    {verdictLabel(helper.verdict)}
                                                </Badge>
                                            </td>
                                            <td className="text-muted px-3 py-1.5">
                                                {helper.reasons.length > 0
                                                    ? helper.reasons
                                                          .map((reason) => reason.detail)
                                                          .join("; ")
                                                    : "свидетельств нет"}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </>
                )}
            </Card>
        </div>
    );
}
