"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { apiFetch, identityHeaders, ApiError } from "@/lib/api";
import type { FieldError, ManifestResponse } from "@/lib/types";

import { ManifestEditor } from "@/features/settings/manifest-editor";

/**
 * Подраздел «Манифест»: правка конфигурации дома (US5, FR-027).
 *
 * Манифест показывается как JSON, сохраняется через хранилище платформы:
 * проверка идёт до записи, ошибки показываются по полям, а запись, теряющая
 * комнаты или устройства, отклоняется (не молчаливое изменение).
 *
 * Черновик хранится отдельно от загруженного манифеста, поэтому правка не
 * синхронизируется эффектом и не затирается обновлением кэша.
 *
 * @returns Редактор манифеста.
 */
export default function ManifestSettingsPage() {
    const [draft, setDraft] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);
    const [fields, setFields] = useState<FieldError[]>([]);

    const current = useQuery({
        queryKey: ["manifest"],
        queryFn: () => apiFetch<ManifestResponse>("/api/v1/manifest"),
    });

    const baseText = useMemo(
        () => (current.data ? JSON.stringify(current.data.manifest, null, 2) : ""),
        [current.data],
    );
    const text = draft ?? baseText;

    const save = useMutation({
        mutationFn: async () => {
            let body: unknown;
            try {
                body = JSON.parse(text);
            } catch {
                throw new SyntaxError("Манифест не является корректным JSON");
            }
            const response = await fetch("/api/v1/manifest", {
                method: "PUT",
                headers: { "Content-Type": "application/json", ...(await identityHeaders()) },
                body: JSON.stringify(body),
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                const error = new ApiError(
                    response.status,
                    payload.error ?? "Не удалось сохранить",
                );
                (error as ApiError & { fields?: FieldError[] }).fields = payload.fields ?? [];
                throw error;
            }
            return (await response.json()) as { status: string };
        },
        onSuccess: () => {
            setFields([]);
            setDraft(null);
            setMessage("Манифест сохранён");
        },
        onError: (error) => {
            setMessage(error instanceof SyntaxError ? error.message : error.message);
            setFields((error as ApiError & { fields?: FieldError[] }).fields ?? []);
        },
    });

    return (
        <div className="space-y-4">
            <h1 className="text-xl font-semibold">Манифест</h1>

            {current.error ? (
                <Card>
                    <p className="text-muted text-sm">
                        {current.error instanceof ApiError
                            ? current.error.message
                            : "Манифест недоступен"}
                    </p>
                </Card>
            ) : null}

            <Card>
                <CardTitle>Конфигурация дома</CardTitle>
                <div className="border-border mt-2 overflow-hidden rounded-md border">
                    <ManifestEditor value={text} onChange={setDraft} />
                </div>

                {fields.length > 0 ? (
                    <ul
                        data-testid="manifest-errors"
                        className="text-danger mt-2 space-y-1 text-sm"
                    >
                        {fields.map((field) => (
                            <li key={`${field.loc}:${field.message}`}>
                                <span className="font-mono">{field.loc || "манифест"}</span>:{" "}
                                {field.message}
                            </li>
                        ))}
                    </ul>
                ) : null}

                <div className="mt-3 flex items-center gap-3">
                    <Button size="sm" disabled={save.isPending} onClick={() => save.mutate()}>
                        {save.isPending ? "Сохраняю…" : "Сохранить"}
                    </Button>
                    {message ? (
                        <span
                            className={save.isError ? "text-danger text-sm" : "text-muted text-sm"}
                        >
                            {message}
                        </span>
                    ) : null}
                </div>
            </Card>
        </div>
    );
}
