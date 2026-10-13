"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { apiFetch, ApiError } from "@/lib/api";
import type { LocationSummary } from "@/lib/types";

interface RoleRow {
    role: string;
    entity: string;
}

/**
 * Правка ролей датчиков локации (спека 017, US5, FR-026).
 *
 * Привязка «роль → сущность» задаётся здесь, а не в YAML руками: правка идёт
 * через манифест (проверка и применение без перезапуска), поэтому интерфейс и
 * файл не расходятся.
 *
 * @param props Локация и её текущие роли.
 * @returns Содержимое диалога правки ролей.
 */
export function LocationRolesEditor({ location }: { location: LocationSummary }) {
    const queryClient = useQueryClient();
    const [rows, setRows] = useState<RoleRow[]>(() =>
        Object.entries(location.sensors ?? {}).map(([role, entity]) => ({ role, entity })),
    );
    const [message, setMessage] = useState<string | null>(null);

    const save = useMutation({
        mutationFn: () =>
            apiFetch(`/api/v1/locations/${encodeURIComponent(location.id)}`, {
                method: "PUT",
                body: JSON.stringify({
                    sensors: Object.fromEntries(
                        rows
                            .filter((row) => row.role.trim() && row.entity.trim())
                            .map((row) => [row.role.trim(), row.entity.trim()]),
                    ),
                }),
            }),
        onSuccess: () => {
            setMessage("Роли сохранены");
            void queryClient.invalidateQueries({ queryKey: ["locations"] });
        },
        onError: (error) =>
            setMessage(error instanceof ApiError ? error.message : "Не удалось сохранить роли"),
    });

    const replace = (index: number, patch: Partial<RoleRow>) =>
        setRows((previous) =>
            previous.map((row, current) => (current === index ? { ...row, ...patch } : row)),
        );

    return (
        <div className="space-y-3">
            <p className="text-muted text-sm">
                Роль датчика → сущность Home Assistant. Пустая строка роли или сущности не
                сохраняется.
            </p>

            {rows.length === 0 ? (
                <p className="text-muted text-sm">Датчиков нет.</p>
            ) : (
                <div className="space-y-2">
                    {rows.map((row, index) => (
                        <div key={index} className="flex gap-2">
                            <input
                                aria-label="Роль"
                                value={row.role}
                                placeholder="temperature"
                                onChange={(event) => replace(index, { role: event.target.value })}
                                className="border-border bg-surface-2 w-40 rounded-md border px-2 py-1 font-mono text-sm"
                            />
                            <input
                                aria-label="Сущность"
                                value={row.entity}
                                placeholder="sensor.t_spalnia"
                                onChange={(event) => replace(index, { entity: event.target.value })}
                                className="border-border bg-surface-2 min-w-0 flex-1 rounded-md border px-2 py-1 font-mono text-sm"
                            />
                            <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setRows(rows.filter((_, i) => i !== index))}
                            >
                                Удалить
                            </Button>
                        </div>
                    ))}
                </div>
            )}

            <div className="flex items-center gap-2">
                <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setRows([...rows, { role: "", entity: "" }])}
                >
                    Добавить датчик
                </Button>
                <Button size="sm" disabled={save.isPending} onClick={() => save.mutate()}>
                    {save.isPending ? "Сохраняю…" : "Сохранить роли"}
                </Button>
                {message ? (
                    <span className={save.isError ? "text-danger text-sm" : "text-muted text-sm"}>
                        {message}
                    </span>
                ) : null}
            </div>
        </div>
    );
}
