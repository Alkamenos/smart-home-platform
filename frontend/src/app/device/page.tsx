"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, ApiError } from "@/lib/api";
import { deviceState } from "@/lib/labels";
import type { DeviceDetail } from "@/lib/types";

import { DeviceControls } from "@/features/devices/device-controls";
import { DecisionPanel } from "@/features/devices/decision-panel";
import { FsmDiagram } from "@/features/devices/fsm-diagram";
import { OverrideBadge } from "@/features/devices/override-badge";

/**
 * Страница прибора: состояние, автоматика, поведения и управление (US2, US3).
 *
 * Идентификатор приходит параметром запроса: статический экспорт не умеет
 * динамические сегменты без предварительной генерации, а устройства появляются
 * во время работы.
 *
 * @returns Страница прибора.
 */
function DeviceView() {
    const params = useSearchParams();
    const id = params.get("id") ?? "";
    const { data, isLoading, error } = useQuery({
        queryKey: ["device", id],
        queryFn: () => apiFetch<DeviceDetail>(`/api/v1/devices/${encodeURIComponent(id)}`),
        enabled: Boolean(id),
    });

    if (!id) {
        return <Card>Не указано устройство.</Card>;
    }
    if (isLoading) {
        return <Skeleton className="h-48" />;
    }
    if (error || !data) {
        return (
            <Card>
                <CardTitle>Не удалось открыть устройство</CardTitle>
                <p className="text-muted mt-2 text-sm">
                    {error instanceof ApiError ? error.message : "Устройство недоступно"}
                </p>
            </Card>
        );
    }

    const raw = data.state && typeof data.state === "object" ? data.state.state : data.state;
    const presentation = deviceState(raw, data.status);
    const isOn = String(raw ?? "").toLowerCase() === "on";

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <Link href="/devices/" className="text-accent text-xs hover:underline">
                    ← Автоматика
                </Link>
            </div>

            <Card>
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <CardTitle className="text-base">
                            {data.name || data.ha_entity_id}
                        </CardTitle>
                        <div className="text-muted font-mono text-xs">{data.ha_entity_id}</div>
                    </div>
                    <Badge variant={presentation.variant}>{presentation.label}</Badge>
                </div>
                <div className="mt-4 space-y-3">
                    <DeviceControls deviceId={data.id} entityId={data.ha_entity_id} isOn={isOn} />
                    <OverrideBadge entityId={data.ha_entity_id} />
                </div>
            </Card>

            <Card>
                <CardTitle>Почему так</CardTitle>
                <div className="mt-2">
                    <DecisionPanel decision={data.decision} />
                </div>
            </Card>

            <Card>
                <CardTitle>Автоматика</CardTitle>
                {data.fsm.length ? (
                    <ul className="mt-2 flex flex-wrap gap-2">
                        {data.fsm.map((state) => (
                            <li key={state.fsm_id} className="flex items-center gap-1.5 text-sm">
                                <Badge variant="info">{state.behavior || "автоматика"}</Badge>
                                <span className="text-muted font-mono">{state.state}</span>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p className="text-muted mt-2 text-sm">
                        {data.automation?.configured
                            ? "Состояние неизвестно"
                            : "Автоматика не настроена."}
                    </p>
                )}
            </Card>

            <Card>
                <details>
                    <summary className="cursor-pointer text-sm font-semibold">
                        Схема автоматики
                    </summary>
                    <div className="mt-3">
                        <FsmDiagram
                            entityId={data.ha_entity_id}
                            currentState={data.fsm[0]?.state}
                        />
                    </div>
                </details>
            </Card>

            <Card>
                <CardTitle>Поведения</CardTitle>
                {data.behaviors.length ? (
                    <ul className="mt-2 space-y-1 text-sm">
                        {data.behaviors.map((behavior) => (
                            <li
                                key={`${behavior.template}:${behavior.priority}`}
                                className="flex gap-2"
                            >
                                <span className="text-muted">{behavior.template}</span>
                                <span className="text-muted">приоритет {behavior.priority}</span>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p className="text-muted mt-2 text-sm">Поведений нет.</p>
                )}
            </Card>
        </div>
    );
}

/**
 * Обёртка с Suspense: чтение параметров запроса требует клиентской границы.
 *
 * @returns Страница прибора.
 */
export default function DevicePage() {
    return (
        <Suspense fallback={<Skeleton className="h-48" />}>
            <DeviceView />
        </Suspense>
    );
}
