"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { apiFetch, ApiError } from "@/lib/api";
import { KIND_LABELS, KIND_OPTIONS, kindLabel } from "@/lib/labels";
import type { LocationSummary } from "@/lib/types";

/**
 * Создание и правка места: имя, вид, родитель (B93).
 *
 * Правка идёт через манифест, поэтому интерфейс и файл не расходятся, а
 * инварианты дерева (родитель существует, без циклов, локация не в комнате)
 * проверяет сервер — интерфейс показывает причину отказа словами.
 *
 * @param props Все места, правимое место (если правка) и признак закрытия.
 * @returns Содержимое диалога места.
 */
export function PlaceEditor({
    places,
    place,
    onDone,
}: {
    places: LocationSummary[];
    place?: LocationSummary;
    onDone?: () => void;
}) {
    const queryClient = useQueryClient();
    const [id, setId] = useState(place?.id ?? "");
    const [name, setName] = useState(place?.name ?? "");
    const [kind, setKind] = useState(place?.kind ?? "outdoor");
    const [parent, setParent] = useState(place?.parent ?? "");
    const [message, setMessage] = useState<string | null>(null);

    const save = useMutation({
        mutationFn: () => {
            const body = JSON.stringify({
                name: name.trim(),
                kind,
                parent: parent || null,
                ...(place ? {} : { id: id.trim() }),
            });
            const path = place
                ? `/api/v1/locations/${encodeURIComponent(place.id)}`
                : "/api/v1/locations";
            return apiFetch(path, { method: place ? "PUT" : "POST", body });
        },
        onSuccess: () => {
            setMessage("Сохранено");
            void queryClient.invalidateQueries({ queryKey: ["locations"] });
            onDone?.();
        },
        onError: (error) =>
            setMessage(error instanceof ApiError ? error.message : "Не удалось сохранить место"),
    });

    // Родителем не может быть само место: цикл отвергнет сервер, но предлагать
    // его в списке — значит предлагать ошибку.
    const parentOptions = places.filter((item) => item.id !== place?.id);

    return (
        <div className="space-y-3">
            <p className="text-muted text-sm">
                Место — комната или локация. Родитель задаёт дерево: «Теплица» внутри «Сада».
            </p>

            {place ? null : (
                <label className="block text-sm">
                    <span className="text-muted">
                        Идентификатор (латиница, цифры, подчёркивание)
                    </span>
                    <input
                        aria-label="Идентификатор"
                        value={id}
                        placeholder="gazon"
                        onChange={(event) => setId(event.target.value)}
                        className="border-border bg-surface-2 mt-1 w-full rounded-md border px-2 py-1 font-mono text-sm"
                    />
                </label>
            )}

            <label className="block text-sm">
                <span className="text-muted">Имя</span>
                <input
                    aria-label="Имя"
                    value={name}
                    placeholder="Газон"
                    onChange={(event) => setName(event.target.value)}
                    className="border-border bg-surface-2 mt-1 w-full rounded-md border px-2 py-1 text-sm"
                />
            </label>

            <label className="block text-sm">
                <span className="text-muted">Вид</span>
                <select
                    aria-label="Вид"
                    value={kind}
                    onChange={(event) => setKind(event.target.value)}
                    className="border-border bg-surface-2 mt-1 w-full rounded-md border px-2 py-1 text-sm"
                >
                    {KIND_OPTIONS.map((option) => (
                        <option key={option} value={option}>
                            {KIND_LABELS[option] ?? option}
                        </option>
                    ))}
                </select>
            </label>

            <label className="block text-sm">
                <span className="text-muted">Верхнее место</span>
                <select
                    aria-label="Верхнее место"
                    value={parent}
                    onChange={(event) => setParent(event.target.value)}
                    className="border-border bg-surface-2 mt-1 w-full rounded-md border px-2 py-1 text-sm"
                >
                    <option value="">— верхний уровень —</option>
                    {parentOptions.map((option) => (
                        <option key={option.id} value={option.id}>
                            {option.name} ({kindLabel(option.kind)})
                        </option>
                    ))}
                </select>
            </label>

            <div className="flex items-center gap-2">
                <Button size="sm" disabled={save.isPending} onClick={() => save.mutate()}>
                    {save.isPending ? "Сохраняю…" : place ? "Сохранить место" : "Создать место"}
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
