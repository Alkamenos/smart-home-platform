"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, ApiError } from "@/lib/api";
import { kindLabel } from "@/lib/labels";
import type { LocationSummary } from "@/lib/types";

import { LocationRolesEditor } from "@/features/settings/location-roles-editor";

/**
 * Подраздел «Локации»: комнаты и зоны, их датчики и роли (US5, FR-026).
 *
 * @returns Список локаций с правкой ролей.
 */
export default function LocationsSettingsPage() {
    const { data, isLoading, error } = useQuery({
        queryKey: ["locations"],
        queryFn: () => apiFetch<{ locations: LocationSummary[] }>("/api/v1/locations"),
    });

    return (
        <div className="space-y-4">
            <h1 className="text-xl font-semibold">Локации</h1>
            <p className="text-muted text-sm">
                Роли датчиков задаются здесь: привязка «роль → сущность» сохраняется в манифест и
                применяется без перезапуска.
            </p>

            {isLoading ? <Skeleton className="h-24" /> : null}
            {error ? (
                <Card>
                    <p className="text-muted text-sm">
                        {error instanceof ApiError ? error.message : "Не удалось получить локации"}
                    </p>
                </Card>
            ) : null}

            <div className="grid gap-3 sm:grid-cols-2">
                {(data?.locations ?? []).map((location) => (
                    <Card key={location.id} className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                            <Link
                                href={`/location/?id=${encodeURIComponent(location.id)}`}
                                className="text-accent font-medium hover:underline"
                            >
                                {location.name}
                            </Link>
                            <div className="text-muted font-mono text-xs">{location.id}</div>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                            <Badge variant="neutral">{kindLabel(location.kind)}</Badge>
                            <Badge variant="info">{location.sensor_count} датч.</Badge>
                            <Dialog>
                                <DialogTrigger asChild>
                                    <Button size="sm" variant="outline">
                                        Роли
                                    </Button>
                                </DialogTrigger>
                                <DialogContent
                                    title={`Роли датчиков: ${location.name}`}
                                    description="Правка через манифест, с проверкой и применением."
                                >
                                    <LocationRolesEditor location={location} />
                                </DialogContent>
                            </Dialog>
                        </div>
                    </Card>
                ))}
            </div>
        </div>
    );
}
