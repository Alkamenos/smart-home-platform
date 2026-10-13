"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { apiFetch, ApiError } from "@/lib/api";
import type { Behavior, DeviceAccess, Overview } from "@/lib/types";

interface BehaviorRow {
    template: string;
    priority: number;
    params: string;
}

/**
 * Превратить поведения устройства в строки формы.
 *
 * @param behaviors Поведения из ответа API.
 * @returns Строки формы.
 */
function toRows(behaviors: Behavior[]): BehaviorRow[] {
    return behaviors.map((behavior) => ({
        template: behavior.template,
        priority: behavior.priority,
        params: JSON.stringify(behavior.params ?? {}, null, 2),
    }));
}

/**
 * Настройка устройств: поведения и права доступа (спека 017, US5, FR-025).
 *
 * Правки хранятся отдельно от загруженных данных (по устройству), поэтому
 * состояние не синхронизируется эффектом: это и чище для React, и не затирает
 * уже сделанные правки при обновлении кэша.
 *
 * @returns Панель настройки устройств.
 */
export function DeviceSettings() {
    const queryClient = useQueryClient();
    const [deviceId, setDeviceId] = useState("");
    const [edits, setEdits] = useState<Record<string, BehaviorRow[]>>({});
    const [message, setMessage] = useState<string | null>(null);

    const overview = useQuery({
        queryKey: ["overview"],
        queryFn: () => apiFetch<Overview>("/api/v1/overview"),
    });
    const devices = overview.data?.devices ?? [];
    const selected = devices.find((device) => device.id === deviceId);

    const detail = useQuery({
        queryKey: ["device", deviceId],
        queryFn: () =>
            apiFetch<{ behaviors: Behavior[] }>(`/api/v1/devices/${encodeURIComponent(deviceId)}`),
        enabled: Boolean(deviceId),
    });

    const baseRows = useMemo(() => toRows(detail.data?.behaviors ?? []), [detail.data]);
    const rows = edits[deviceId] ?? baseRows;

    const updateRows = (next: BehaviorRow[]) => {
        setEdits((previous) => ({ ...previous, [deviceId]: next }));
    };

    const saveBehaviors = useMutation({
        mutationFn: () => {
            const payload = rows.map((row) => ({
                template: row.template,
                priority: row.priority,
                params: row.params.trim() ? JSON.parse(row.params) : {},
            }));
            return apiFetch(`/api/v1/devices/${encodeURIComponent(deviceId)}/behaviors`, {
                method: "PUT",
                body: JSON.stringify({ behaviors: payload }),
            });
        },
        onSuccess: () => {
            setMessage("Поведения сохранены");
            setEdits((previous) => {
                const next = { ...previous };
                delete next[deviceId];
                return next;
            });
            void queryClient.invalidateQueries({ queryKey: ["device", deviceId] });
            void queryClient.invalidateQueries({ queryKey: ["overview"] });
        },
        onError: (error) =>
            setMessage(
                error instanceof SyntaxError
                    ? "Параметры должны быть корректным JSON"
                    : error instanceof ApiError
                      ? error.message
                      : "Не удалось сохранить поведения",
            ),
    });

    return (
        <div className="space-y-4">
            <h1 className="text-xl font-semibold">Устройства</h1>

            <Card>
                <label className="block text-sm">
                    <span className="text-muted">Устройство</span>
                    <select
                        value={deviceId}
                        onChange={(event) => setDeviceId(event.target.value)}
                        className="border-border bg-surface-2 mt-1 w-full rounded-md border px-2 py-1"
                    >
                        <option value="">— выберите —</option>
                        {devices.map((device) => (
                            <option key={device.id} value={device.id}>
                                {device.name || device.ha_entity_id}
                            </option>
                        ))}
                    </select>
                </label>
            </Card>

            {selected ? (
                <>
                    <Card>
                        <div className="mb-3 flex items-center justify-between">
                            <CardTitle>Поведения</CardTitle>
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() =>
                                    updateRows([
                                        ...rows,
                                        { template: "", priority: 10, params: "{}" },
                                    ])
                                }
                            >
                                Добавить
                            </Button>
                        </div>
                        {rows.length === 0 ? (
                            <p className="text-muted text-sm">Поведений нет.</p>
                        ) : (
                            <div className="space-y-3">
                                {rows.map((row, index) => (
                                    <div
                                        key={index}
                                        className="border-border rounded-md border p-3"
                                    >
                                        <div className="mb-2 flex gap-2">
                                            <input
                                                aria-label="Шаблон"
                                                value={row.template}
                                                placeholder="шаблон"
                                                onChange={(event) =>
                                                    updateRows(
                                                        replace(rows, index, {
                                                            template: event.target.value,
                                                        }),
                                                    )
                                                }
                                                className="border-border bg-surface-2 flex-1 rounded-md border px-2 py-1 font-mono text-sm"
                                            />
                                            <input
                                                aria-label="Приоритет"
                                                type="number"
                                                min={1}
                                                max={100}
                                                value={row.priority}
                                                onChange={(event) =>
                                                    updateRows(
                                                        replace(rows, index, {
                                                            priority: Number(event.target.value),
                                                        }),
                                                    )
                                                }
                                                className="border-border bg-surface-2 w-24 rounded-md border px-2 py-1 text-sm"
                                            />
                                            <Button
                                                size="sm"
                                                variant="ghost"
                                                onClick={() =>
                                                    updateRows(rows.filter((_, i) => i !== index))
                                                }
                                            >
                                                Удалить
                                            </Button>
                                        </div>
                                        <textarea
                                            aria-label="Параметры"
                                            value={row.params}
                                            onChange={(event) =>
                                                updateRows(
                                                    replace(rows, index, {
                                                        params: event.target.value,
                                                    }),
                                                )
                                            }
                                            rows={3}
                                            className="border-border bg-surface-2 w-full rounded-md border px-2 py-1 font-mono text-xs"
                                        />
                                    </div>
                                ))}
                            </div>
                        )}
                        <div className="mt-3 flex items-center gap-3">
                            <Button
                                size="sm"
                                disabled={saveBehaviors.isPending || !deviceId}
                                onClick={() => saveBehaviors.mutate()}
                            >
                                Сохранить поведения
                            </Button>
                            {message ? <span className="text-muted text-sm">{message}</span> : null}
                        </div>
                    </Card>

                    <AccessPanel deviceId={deviceId} />
                </>
            ) : null}
        </div>
    );
}

/**
 * Права доступа к прибору (US5).
 *
 * @param props Идентификатор устройства.
 * @returns Список прав и форма назначения.
 */
function AccessPanel({ deviceId }: { deviceId: string }) {
    const queryClient = useQueryClient();
    const [userId, setUserId] = useState("");
    const [role, setRole] = useState("viewer");

    const accesses = useQuery({
        queryKey: ["access", deviceId],
        queryFn: () =>
            apiFetch<DeviceAccess[]>(`/api/v1/devices/${encodeURIComponent(deviceId)}/access`),
        enabled: Boolean(deviceId),
    });

    const grant = useMutation({
        mutationFn: () =>
            apiFetch(`/api/v1/devices/${encodeURIComponent(deviceId)}/access`, {
                method: "POST",
                body: JSON.stringify({ user_id: userId, role }),
            }),
        onSuccess: () => {
            setUserId("");
            void queryClient.invalidateQueries({ queryKey: ["access", deviceId] });
        },
    });

    const revoke = useMutation({
        mutationFn: (accessId: string) =>
            apiFetch(
                `/api/v1/devices/${encodeURIComponent(deviceId)}/access/${encodeURIComponent(accessId)}`,
                { method: "DELETE" },
            ),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ["access", deviceId] }),
    });

    return (
        <Card>
            <CardTitle>Права доступа</CardTitle>
            {(accesses.data ?? []).length === 0 ? (
                <p className="text-muted mt-2 text-sm">Отдельных прав нет.</p>
            ) : (
                <ul className="mt-2 space-y-1 text-sm">
                    {(accesses.data ?? []).map((access) => (
                        <li key={access.id} className="flex items-center gap-3">
                            <span className="font-mono">{access.user_id}</span>
                            <span className="text-muted">{access.role}</span>
                            <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => revoke.mutate(access.id)}
                            >
                                Отозвать
                            </Button>
                        </li>
                    ))}
                </ul>
            )}

            <div className="mt-3 flex flex-wrap items-end gap-2">
                <label className="text-sm">
                    <span className="text-muted">Пользователь</span>
                    <input
                        value={userId}
                        onChange={(event) => setUserId(event.target.value)}
                        className="border-border bg-surface-2 mt-1 block rounded-md border px-2 py-1"
                    />
                </label>
                <label className="text-sm">
                    <span className="text-muted">Роль</span>
                    <select
                        value={role}
                        onChange={(event) => setRole(event.target.value)}
                        className="border-border bg-surface-2 mt-1 block rounded-md border px-2 py-1"
                    >
                        <option value="viewer">viewer</option>
                        <option value="controller">controller</option>
                    </select>
                </label>
                <Button
                    size="sm"
                    disabled={!userId || grant.isPending}
                    onClick={() => grant.mutate()}
                >
                    Назначить
                </Button>
            </div>
        </Card>
    );
}

/**
 * Заменить строку поведений, не мутируя массив.
 *
 * @param rows Текущие строки.
 * @param index Индекс строки.
 * @param patch Изменения.
 * @returns Новый массив строк.
 */
function replace(rows: BehaviorRow[], index: number, patch: Partial<BehaviorRow>): BehaviorRow[] {
    return rows.map((row, current) => (current === index ? { ...row, ...patch } : row));
}
