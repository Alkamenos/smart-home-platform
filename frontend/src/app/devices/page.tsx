"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, ApiError } from "@/lib/api";
import type { Overview } from "@/lib/types";

import { DeviceGrid } from "@/features/devices/device-grid";
import { useLiveOverview } from "@/features/home/use-live-overview";

/**
 * Раздел «Автоматика»: приборы дома в виде дата-грида (US2, US3).
 *
 * @returns Грид приборов с поиском, фильтрами, сортировкой и группировкой.
 */
export default function DevicesPage() {
    useLiveOverview();
    const { data, isLoading, error } = useQuery({
        queryKey: ["overview"],
        queryFn: () => apiFetch<Overview>("/api/v1/overview"),
    });

    return (
        <div className="space-y-4">
            <h1 className="text-xl font-semibold">Автоматика</h1>

            {isLoading ? <Skeleton className="h-64" /> : null}

            {error ? (
                <Card>
                    <CardTitle>Не удалось получить устройства</CardTitle>
                    <p className="text-muted mt-2 text-sm">
                        {error instanceof ApiError ? error.message : String(error)}
                    </p>
                </Card>
            ) : null}

            {data ? <DeviceGrid devices={data.devices} /> : null}
        </div>
    );
}
