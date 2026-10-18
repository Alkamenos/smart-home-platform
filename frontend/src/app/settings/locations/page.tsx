"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, ApiError } from "@/lib/api";
import { deviceTypeLabel, kindLabel } from "@/lib/labels";
import type { LocationSummary } from "@/lib/types";

import { DeviceMover } from "@/features/settings/device-mover";
import { LocationRolesEditor } from "@/features/settings/location-roles-editor";
import { PlaceEditor } from "@/features/settings/place-editor";

/**
 * Дети места: у кого родитель — этот идентификатор.
 *
 * @param places Все места.
 * @param parent Идентификатор родителя либо null для верхнего уровня.
 * @returns Места в порядке объявления.
 */
function childrenOf(places: LocationSummary[], parent: string | null): LocationSummary[] {
    return places.filter((place) => (place.parent ?? null) === parent);
}

/**
 * Карточка места: подпись, приборы и действия, затем вложенные места.
 *
 * @param props Место, все места и глубина в дереве.
 * @returns Карточка места с детьми.
 */
function PlaceCard({
    place,
    places,
    depth,
}: {
    place: LocationSummary;
    places: LocationSummary[];
    depth: number;
}) {
    const queryClient = useQueryClient();
    const [removeMessage, setRemoveMessage] = useState<string | null>(null);

    const remove = useMutation({
        mutationFn: () =>
            apiFetch(`/api/v1/locations/${encodeURIComponent(place.id)}`, { method: "DELETE" }),
        onSuccess: () => {
            setRemoveMessage(null);
            void queryClient.invalidateQueries({ queryKey: ["locations"] });
        },
        onError: (error) =>
            setRemoveMessage(
                error instanceof ApiError ? error.message : "Не удалось удалить место",
            ),
    });

    const devices = place.devices ?? [];
    const children = childrenOf(places, place.id);
    const empty = devices.length === 0 && place.sensor_count === 0 && children.length === 0;

    return (
        <div className="space-y-2" style={{ marginLeft: depth * 18 }}>
            <Card className="space-y-2">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                        <Link
                            href={`/location/?id=${encodeURIComponent(place.id)}`}
                            className="text-accent font-medium hover:underline"
                        >
                            {place.name}
                        </Link>
                        <div className="text-muted font-mono text-xs">{place.id}</div>
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center gap-2">
                        <Badge variant="neutral">{kindLabel(place.kind)}</Badge>
                        <Badge variant="info">{place.sensor_count} датч.</Badge>
                        <Badge variant="neutral">{devices.length} приб.</Badge>
                        <Dialog>
                            <DialogTrigger asChild>
                                <Button size="sm" variant="outline">
                                    Изменить
                                </Button>
                            </DialogTrigger>
                            <DialogContent
                                title={`Место: ${place.name}`}
                                description="Имя, вид и верхнее место. Дерево проверяется при сохранении."
                            >
                                <PlaceEditor places={places} place={place} />
                            </DialogContent>
                        </Dialog>
                        <Dialog>
                            <DialogTrigger asChild>
                                <Button size="sm" variant="outline">
                                    Роли
                                </Button>
                            </DialogTrigger>
                            <DialogContent
                                title={`Роли датчиков: ${place.name}`}
                                description="Правка через манифест, с проверкой и применением."
                            >
                                <LocationRolesEditor location={place} />
                            </DialogContent>
                        </Dialog>
                        <Button
                            size="sm"
                            variant="ghost"
                            disabled={!empty || remove.isPending}
                            title={
                                empty
                                    ? "Удалить пустое место"
                                    : "Сначала перенесите приборы и датчики"
                            }
                            onClick={() => remove.mutate()}
                        >
                            Удалить
                        </Button>
                    </div>
                </div>

                {devices.length ? (
                    <ul className="space-y-1">
                        {devices.map((device) => (
                            <li
                                key={device.id}
                                className="flex flex-wrap items-center justify-between gap-2 text-sm"
                            >
                                <span className="min-w-0">
                                    {device.name}{" "}
                                    <span className="text-muted">
                                        ({deviceTypeLabel(device.type)}
                                        {device.behaviors ? `, автоматов ${device.behaviors}` : ""})
                                    </span>{" "}
                                    <span className="text-muted font-mono text-xs">
                                        {device.id}
                                    </span>
                                </span>
                                <Dialog>
                                    <DialogTrigger asChild>
                                        <Button size="sm" variant="ghost">
                                            Переместить
                                        </Button>
                                    </DialogTrigger>
                                    <DialogContent
                                        title="Перенос прибора"
                                        description="Прибор уйдёт из этого места и появится в выбранном."
                                    >
                                        <DeviceMover device={device} places={places} />
                                    </DialogContent>
                                </Dialog>
                            </li>
                        ))}
                    </ul>
                ) : null}

                {removeMessage ? <p className="text-danger text-sm">{removeMessage}</p> : null}
            </Card>

            {children.map((child) => (
                <PlaceCard key={child.id} place={child} places={places} depth={depth + 1} />
            ))}
        </div>
    );
}

/**
 * Подраздел «Локации»: дерево мест, их приборы, роли датчиков и перенос приборов.
 *
 * Место — комната или локация; дерево задаётся родителем (B93). Правка идёт
 * через манифест: интерфейс и файл не расходятся, инварианты проверяет сервер.
 *
 * @returns Дерево мест с правкой.
 */
export default function LocationsSettingsPage() {
    const { data, isLoading, error } = useQuery({
        queryKey: ["locations"],
        queryFn: () => apiFetch<{ locations: LocationSummary[] }>("/api/v1/locations"),
    });

    const places = data?.locations ?? [];
    const roots = childrenOf(places, null);

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <h1 className="text-xl font-semibold">Локации</h1>
                <Dialog>
                    <DialogTrigger asChild>
                        <Button size="sm">Создать место</Button>
                    </DialogTrigger>
                    <DialogContent
                        title="Новое место"
                        description="Комната или локация; верхнее место задаёт дерево."
                    >
                        <PlaceEditor places={places} />
                    </DialogContent>
                </Dialog>
            </div>
            <p className="text-muted text-sm">
                Дерево мест: комнаты дома и то, что на улице. Здесь правятся имя, вид и верхнее
                место, переносятся приборы и задаются роли датчиков.
            </p>

            {isLoading ? <Skeleton className="h-24" /> : null}
            {error ? (
                <Card>
                    <p className="text-muted text-sm">
                        {error instanceof ApiError ? error.message : "Не удалось получить локации"}
                    </p>
                </Card>
            ) : null}

            {roots.map((place) => (
                <PlaceCard key={place.id} place={place} places={places} depth={0} />
            ))}
        </div>
    );
}
