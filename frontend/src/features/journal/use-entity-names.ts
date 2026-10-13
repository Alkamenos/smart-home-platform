"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { apiFetch } from "@/lib/api";
import type { Overview } from "@/lib/types";

/**
 * Карта «сущность → человекочитаемое имя» для журнала (спека 017, US4).
 *
 * В журнале записи названы идентификаторами Home Assistant; инженеру нужнее имя
 * прибора, а идентификатор — второстепенно (и копируется по клику).
 *
 * @returns Функция перевода сущности в имя.
 */
export function useEntityNames(): (entityId: string) => string {
    const { data } = useQuery({
        queryKey: ["overview"],
        queryFn: () => apiFetch<Overview>("/api/v1/overview"),
        staleTime: 60_000,
    });
    return useMemo(() => {
        const map = new Map<string, string>();
        for (const device of data?.devices ?? []) {
            if (device.name) {
                map.set(device.ha_entity_id, device.name);
            }
        }
        return (entityId: string) => map.get(entityId) ?? entityId;
    }, [data]);
}
