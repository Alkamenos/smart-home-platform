"use client";

import { useQuery } from "@tanstack/react-query";
import { House, Wifi, WifiOff } from "lucide-react";
import Link from "next/link";

import { Card, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, ApiError } from "@/lib/api";
import type { Overview } from "@/lib/types";

import { DeviceGrid } from "@/features/devices/device-grid";
import { AlertsPanel } from "@/features/home/alerts-panel";
import { LocationGrid } from "@/features/home/location-grid";
import { useLiveOverview } from "@/features/home/use-live-overview";

/**
 * Раздел «Дом»: что сейчас с домом и что требует внимания (US1).
 *
 * @returns Первый экран.
 */
export default function HomePage() {
    const connected = useLiveOverview();
    const { data, isLoading, error } = useQuery({
        queryKey: ["overview"],
        queryFn: () => apiFetch<Overview>("/api/v1/overview"),
        refetchInterval: 60_000,
    });

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between gap-3">
                <h1 className="flex min-w-0 items-center gap-2 text-xl font-semibold">
                    <House className="text-accent size-6 shrink-0" aria-hidden />
                    <span className="truncate">{data?.house_name || "Дом"}</span>
                </h1>
                <span
                    className="text-muted inline-flex shrink-0 items-center gap-1.5 text-xs"
                    title={
                        connected
                            ? "канал живых обновлений подключён"
                            : "канал живых обновлений отключён"
                    }
                >
                    {connected ? (
                        <Wifi className="text-success size-4" aria-hidden />
                    ) : (
                        <WifiOff className="text-warning size-4" aria-hidden />
                    )}
                    {connected ? "WS подключён" : "WS отключён"}
                </span>
            </div>

            {isLoading ? <HomeSkeleton /> : null}

            {error ? (
                <Card>
                    <CardTitle>Не удалось получить состояние дома</CardTitle>
                    <p className="text-muted mt-2 text-sm">
                        {error instanceof ApiError && error.status === 503
                            ? "Платформа не собрана: движок автоматики недоступен."
                            : error.message}
                    </p>
                </Card>
            ) : null}

            {data ? (
                <>
                    <AlertsPanel alerts={data.alerts ?? []} />

                    <section className="space-y-3">
                        <h2 className="text-muted text-sm font-semibold tracking-wide">Локации</h2>
                        {data.locations.length === 0 ? (
                            <p className="text-muted text-sm">
                                Данных нет: локации не описаны в манифесте.
                            </p>
                        ) : (
                            <LocationGrid locations={data.locations} />
                        )}
                    </section>

                    <section className="space-y-3">
                        <div className="flex items-center justify-between">
                            <h2 className="text-muted text-sm font-semibold tracking-wide">
                                Приборы
                            </h2>
                            <Link href="/devices/" className="text-accent text-xs hover:underline">
                                Автоматика
                            </Link>
                        </div>
                        {data.devices.length === 0 ? (
                            <p className="text-muted text-sm">
                                Данных нет: устройства не подключены.
                            </p>
                        ) : (
                            <DeviceGrid devices={data.devices} />
                        )}
                    </section>
                </>
            ) : null}
        </div>
    );
}

/**
 * Заглушка загрузки первого экрана.
 *
 * @returns Скелетон.
 */
function HomeSkeleton() {
    return (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className="h-32" />
            ))}
        </div>
    );
}
