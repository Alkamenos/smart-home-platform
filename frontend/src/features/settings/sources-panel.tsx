"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { apiFetch, ApiError } from "@/lib/api";
import type { DiscoveryData, RoomOption, Source } from "@/lib/types";

import { validateSource, type FieldErrors } from "@/features/settings/source-validation";

/**
 * Импорт устройств из источника (US5, FR-024).
 *
 * @param props Источник, из которого импортируем.
 * @returns Содержимое диалога: сущности, выбор комнаты и результат.
 */
function DiscoveryContent({ source }: { source: Source }) {
    const queryClient = useQueryClient();
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [room, setRoom] = useState("");
    const [result, setResult] = useState<string | null>(null);

    const discovery = useQuery({
        queryKey: ["discovery", source.id],
        queryFn: () =>
            apiFetch<DiscoveryData>(`/api/v1/devices/sources/${source.id}/discovery-data`),
    });
    const rooms = useQuery({
        queryKey: ["rooms"],
        queryFn: () => apiFetch<{ rooms: RoomOption[] }>("/api/rooms"),
    });

    const apply = useMutation({
        mutationFn: () =>
            apiFetch<{ devices_added: number; devices_updated: number; failed: number }>(
                "/api/v1/devices/apply",
                {
                    method: "POST",
                    body: JSON.stringify({
                        source_id: source.id,
                        selections: [...selected].map((entityId) => ({
                            device_entity_id: entityId,
                            target_room: room || undefined,
                        })),
                    }),
                },
            ),
        onSuccess: (data) => {
            setResult(
                `Добавлено: ${data.devices_added}, обновлено: ${data.devices_updated}, ошибок: ${data.failed}`,
            );
            void queryClient.invalidateQueries({ queryKey: ["overview"] });
            void queryClient.invalidateQueries({ queryKey: ["devices"] });
        },
        onError: (error) => setResult(error instanceof ApiError ? error.message : String(error)),
    });

    const toggle = (entityId: string) => {
        setSelected((previous) => {
            const next = new Set(previous);
            if (next.has(entityId)) {
                next.delete(entityId);
            } else {
                next.add(entityId);
            }
            return next;
        });
    };

    if (discovery.isLoading) {
        return <p className="text-muted text-sm">Читаю устройства источника…</p>;
    }
    if (discovery.error) {
        return (
            <p className="text-danger text-sm">
                {discovery.error instanceof ApiError
                    ? discovery.error.message
                    : "Не удалось получить данные источника"}
            </p>
        );
    }

    const data = discovery.data;
    if (data?.error) {
        return <p className="text-danger text-sm">{data.error}</p>;
    }

    return (
        <div className="space-y-3">
            <label className="flex items-center gap-2 text-sm">
                <span className="text-muted">Комната</span>
                <select
                    value={room}
                    onChange={(event) => setRoom(event.target.value)}
                    className="border-border bg-surface-2 rounded-md border px-2 py-1 text-sm"
                >
                    <option value="">по умолчанию</option>
                    {(rooms.data?.rooms ?? []).map((option) => (
                        <option key={option.id} value={option.id}>
                            {option.name}
                        </option>
                    ))}
                </select>
            </label>

            <div className="border-border max-h-72 overflow-auto rounded-md border">
                {(data?.available_devices ?? []).length === 0 ? (
                    <p className="text-muted p-3 text-sm">Источник не отдал ни одной сущности.</p>
                ) : (
                    (data?.available_devices ?? []).map((device) => (
                        <label
                            key={device.entity_id}
                            className="border-border/60 flex items-center gap-2 border-b px-3 py-2 text-sm"
                        >
                            <input
                                type="checkbox"
                                checked={selected.has(device.entity_id)}
                                onChange={() => toggle(device.entity_id)}
                            />
                            <span className="min-w-0 flex-1 truncate">
                                {device.friendly_name}
                                <span className="text-muted ml-2 font-mono text-xs">
                                    {device.entity_id}
                                </span>
                            </span>
                            {device.area_name ? (
                                <Badge variant="neutral">{device.area_name}</Badge>
                            ) : null}
                        </label>
                    ))
                )}
            </div>

            <div className="flex justify-end gap-2">
                {result ? <span className="text-muted mr-auto text-sm">{result}</span> : null}
                <Button
                    size="sm"
                    disabled={selected.size === 0 || apply.isPending}
                    onClick={() => apply.mutate()}
                >
                    {apply.isPending ? "Импортирую…" : `Импортировать (${selected.size})`}
                </Button>
            </div>
        </div>
    );
}

/**
 * Раздел «Источники»: подключение Home Assistant и импорт (US5).
 *
 * @returns Управление источниками.
 */
export function SourcesPanel() {
    const queryClient = useQueryClient();
    const [createOpen, setCreateOpen] = useState(false);
    const [form, setForm] = useState({ name: "", url: "", token: "" });
    const [errors, setErrors] = useState<FieldErrors>({});
    const [formError, setFormError] = useState<string | null>(null);

    const sources = useQuery({
        queryKey: ["sources"],
        queryFn: () => apiFetch<Source[]>("/api/v1/devices/sources"),
    });

    const create = useMutation({
        mutationFn: () =>
            apiFetch<Source>("/api/v1/devices/sources", {
                method: "POST",
                body: JSON.stringify(form),
            }),
        onSuccess: () => {
            setCreateOpen(false);
            setForm({ name: "", url: "", token: "" });
            setFormError(null);
            void queryClient.invalidateQueries({ queryKey: ["sources"] });
        },
        onError: (error) =>
            setFormError(error instanceof ApiError ? error.message : "Не удалось создать источник"),
    });

    const sync = useMutation({
        mutationFn: (sourceId: string) =>
            apiFetch(`/api/v1/devices/sources/${sourceId}/sync`, { method: "POST" }),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sources"] }),
    });

    const submit = () => {
        const validation = validateSource(form);
        setErrors(validation);
        if (Object.keys(validation).length > 0) {
            return;
        }
        create.mutate();
    };

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <h1 className="text-xl font-semibold">Источники</h1>
                <Dialog open={createOpen} onOpenChange={setCreateOpen}>
                    <DialogTrigger asChild>
                        <Button size="sm">Добавить источник</Button>
                    </DialogTrigger>
                    <DialogContent
                        title="Новый источник"
                        description="Подключение Home Assistant по REST API."
                    >
                        <div className="space-y-3">
                            <Field
                                label="Название"
                                value={form.name}
                                error={errors.name}
                                onChange={(value) => setForm({ ...form, name: value })}
                            />
                            <Field
                                label="Адрес"
                                value={form.url}
                                error={errors.url}
                                placeholder="http://192.168.1.10:8123"
                                onChange={(value) => setForm({ ...form, url: value })}
                            />
                            <Field
                                label="Токен"
                                value={form.token}
                                error={errors.token}
                                onChange={(value) => setForm({ ...form, token: value })}
                            />
                            {formError ? <p className="text-danger text-sm">{formError}</p> : null}
                            <div className="flex justify-end">
                                <Button size="sm" disabled={create.isPending} onClick={submit}>
                                    Сохранить
                                </Button>
                            </div>
                        </div>
                    </DialogContent>
                </Dialog>
            </div>

            {sources.isLoading ? <p className="text-muted text-sm">Загрузка…</p> : null}
            {sources.error ? (
                <Card>
                    <p className="text-muted text-sm">
                        {sources.error instanceof ApiError
                            ? sources.error.message
                            : "Не удалось получить источники"}
                    </p>
                </Card>
            ) : null}

            <div className="grid gap-3 sm:grid-cols-2">
                {(sources.data ?? []).map((source) => (
                    <Card key={source.id} data-testid="source-card">
                        <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                                <CardTitle className="truncate">{source.name}</CardTitle>
                                <div className="text-muted truncate font-mono text-xs">
                                    {source.url}
                                </div>
                            </div>
                            <Badge variant={source.status === "connected" ? "success" : "warning"}>
                                {source.status === "connected" ? "подключён" : "нет связи"}
                            </Badge>
                        </div>
                        {source.last_error ? (
                            <p className="text-danger mt-2 text-xs">{source.last_error}</p>
                        ) : null}
                        <div className="mt-3 flex gap-2">
                            <Button
                                size="sm"
                                variant="outline"
                                disabled={sync.isPending}
                                onClick={() => sync.mutate(source.id)}
                            >
                                Синхронизировать
                            </Button>
                            <Dialog>
                                <DialogTrigger asChild>
                                    <Button size="sm" variant="ghost">
                                        Сущности
                                    </Button>
                                </DialogTrigger>
                                <DialogContent title="Импорт устройств">
                                    <DiscoveryContent source={source} />
                                </DialogContent>
                            </Dialog>
                        </div>
                    </Card>
                ))}
            </div>

            {sources.data && sources.data.length === 0 ? (
                <Card>
                    <p className="text-muted text-sm">Источников нет: добавьте Home Assistant.</p>
                </Card>
            ) : null}
        </div>
    );
}

/**
 * Поле формы с ошибкой по полю.
 *
 * @param props Подпись, значение, ошибка и обработчик.
 * @returns Строка формы.
 */
function Field({
    label,
    value,
    error,
    placeholder,
    onChange,
}: {
    label: string;
    value: string;
    error?: string;
    placeholder?: string;
    onChange: (value: string) => void;
}) {
    return (
        <label className="block text-sm">
            <span className="text-muted">{label}</span>
            <input
                value={value}
                placeholder={placeholder}
                onChange={(event) => onChange(event.target.value)}
                className="border-border bg-surface-2 mt-1 w-full rounded-md border px-2 py-1"
            />
            {error ? <span className="text-danger mt-1 block text-xs">{error}</span> : null}
        </label>
    );
}
