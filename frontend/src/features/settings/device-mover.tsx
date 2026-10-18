"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { apiFetch, ApiError } from "@/lib/api";
import { deviceTypeLabel, kindLabel } from "@/lib/labels";
import type { LocationSummary, PlaceDevice } from "@/lib/types";

/**
 * Перенос прибора в другое место (B93).
 *
 * Прибор описан в манифесте один раз, поэтому перенос — это «взять отсюда и
 * положить туда». Автоматика прибора не меняется: правила поведения остаются с
 * ним, место нужно для правил «комнат без окон» и для панели дома.
 *
 * @param props Прибор, все места и признак закрытия.
 * @returns Содержимое диалога переноса.
 */
export function DeviceMover({
    device,
    places,
    onDone,
}: {
    device: PlaceDevice;
    places: LocationSummary[];
    onDone?: () => void;
}) {
    const queryClient = useQueryClient();
    const [target, setTarget] = useState("");
    const [message, setMessage] = useState<string | null>(null);

    const move = useMutation({
        mutationFn: () =>
            apiFetch(`/api/v1/locations/${encodeURIComponent(target)}/devices`, {
                method: "POST",
                body: JSON.stringify({ device_id: device.id }),
            }),
        onSuccess: () => {
            setMessage("Перенесено");
            void queryClient.invalidateQueries({ queryKey: ["locations"] });
            onDone?.();
        },
        onError: (error) =>
            setMessage(error instanceof ApiError ? error.message : "Не удалось перенести прибор"),
    });

    return (
        <div className="space-y-3">
            <p className="text-sm">
                {device.name} <span className="text-muted">({deviceTypeLabel(device.type)})</span>
                <br />
                <span className="text-muted font-mono text-xs">{device.id}</span>
            </p>

            <label className="block text-sm">
                <span className="text-muted">Куда перенести</span>
                <select
                    aria-label="Куда перенести"
                    value={target}
                    onChange={(event) => setTarget(event.target.value)}
                    className="border-border bg-surface-2 mt-1 w-full rounded-md border px-2 py-1 text-sm"
                >
                    <option value="">— выберите место —</option>
                    {places.map((place) => (
                        <option key={place.id} value={place.id}>
                            {place.name} ({kindLabel(place.kind)})
                        </option>
                    ))}
                </select>
            </label>

            <div className="flex items-center gap-2">
                <Button
                    size="sm"
                    disabled={move.isPending || !target}
                    onClick={() => move.mutate()}
                >
                    {move.isPending ? "Переношу…" : "Перенести"}
                </Button>
                {message ? (
                    <span className={move.isError ? "text-danger text-sm" : "text-muted text-sm"}>
                        {message}
                    </span>
                ) : null}
            </div>
        </div>
    );
}
