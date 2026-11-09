"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { Problem, ProblemLevel, ProblemsSnapshot } from "@/lib/types";

/** Подписи уровней для человека. */
const LEVEL_LABELS: Record<ProblemLevel, string> = {
    critical: "КРИТИЧНО",
    warning: "ВНИМАНИЕ",
    info: "ИНФО",
};

/** Вариант значка по уровню. */
const LEVEL_VARIANT: Record<ProblemLevel, "danger" | "warning" | "neutral"> = {
    critical: "danger",
    warning: "warning",
    info: "neutral",
};

/**
 * Загрузить единый список проблем.
 *
 * @returns Снимок проблем.
 */
async function fetchProblems(): Promise<ProblemsSnapshot> {
    return apiFetch<ProblemsSnapshot>("/api/v1/problems");
}

/**
 * Время проблемы по часам браузера.
 *
 * @param value ISO-8601 или null.
 * @returns Короткая строка времени.
 */
function formatMoment(value: string | null): string {
    if (!value) {
        return "—";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return value;
    }
    return date.toLocaleString("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });
}

/**
 * Раздел «Проблемы дома»: все причины в одном списке.
 *
 * @returns Страница проблем.
 */
export default function ProblemsPage() {
    const query = useQuery({ queryKey: ["problems"], queryFn: fetchProblems });
    const [level, setLevel] = useState<ProblemLevel | "all">("all");

    const problems = useMemo(() => {
        const items = query.data?.problems ?? [];
        return level === "all" ? items : items.filter((item) => item.level === level);
    }, [query.data?.problems, level]);

    if (query.isLoading) {
        return (
            <main className="mx-auto max-w-4xl space-y-3 p-4" data-testid="problems-page">
                <Skeleton className="h-8 w-56" />
                <Skeleton className="h-24 w-full" />
            </main>
        );
    }

    if (query.isError) {
        return (
            <main className="mx-auto max-w-4xl space-y-3 p-4" data-testid="problems-page">
                <Card>
                    <CardTitle>Проблемы дома</CardTitle>
                    <p className="text-danger mt-2 text-sm">Список не загрузился.</p>
                </Card>
            </main>
        );
    }

    const snapshot = query.data;
    const counts = snapshot?.levels ?? { info: 0, warning: 0, critical: 0 };

    return (
        <main className="mx-auto max-w-4xl space-y-4 p-4" data-testid="problems-page">
            <header className="flex flex-wrap items-end justify-between gap-2">
                <div>
                    <h1 className="text-xl font-semibold">Проблемы дома</h1>
                    <p className="text-muted text-sm">
                        Обход датчиков, сторож автоматов и неприменённые команды — в одном месте.
                    </p>
                </div>
                <span className="text-muted text-sm">
                    Обновлено: {formatMoment(snapshot?.generated_at ?? null)}
                </span>
            </header>

            <div className="flex flex-wrap gap-2" role="group" aria-label="Фильтр по уровню">
                <FilterButton active={level === "all"} onClick={() => setLevel("all")}>
                    Все ({snapshot?.count ?? 0})
                </FilterButton>
                <FilterButton active={level === "critical"} onClick={() => setLevel("critical")}>
                    Критичные ({counts.critical})
                </FilterButton>
                <FilterButton active={level === "warning"} onClick={() => setLevel("warning")}>
                    Предупреждения ({counts.warning})
                </FilterButton>
                <FilterButton active={level === "info"} onClick={() => setLevel("info")}>
                    Информация ({counts.info})
                </FilterButton>
            </div>

            {problems.length === 0 ? (
                <Card>
                    <p className="text-muted text-sm">Проблем нет.</p>
                </Card>
            ) : (
                <ul className="space-y-3">
                    {problems.map((problem) => (
                        <li key={problem.id}>
                            <ProblemCard problem={problem} />
                        </li>
                    ))}
                </ul>
            )}

            <p className="text-muted text-xs">
                Подробности по датчикам —{" "}
                <Link className="underline" href="/settings/sources/">
                    в источниках
                </Link>
                , история решений —{" "}
                <Link className="underline" href="/journal/">
                    в журнале
                </Link>
                .
            </p>
        </main>
    );
}

/**
 * Кнопка фильтра.
 *
 * @param props Активна ли и обработчик.
 * @returns Кнопка.
 */
function FilterButton({
    active,
    onClick,
    children,
}: {
    active: boolean;
    onClick: () => void;
    children: ReactNode;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            aria-pressed={active}
            className={
                active
                    ? "bg-surface-2 text-foreground rounded-md px-3 py-1 text-sm"
                    : "text-muted hover:bg-surface-2 rounded-md px-3 py-1 text-sm"
            }
        >
            {children}
        </button>
    );
}

/**
 * Карточка одной проблемы.
 *
 * @param props Проблема.
 * @returns Карточка.
 */
function ProblemCard({ problem }: { problem: Problem }) {
    return (
        <Card>
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={LEVEL_VARIANT[problem.level]}>
                            {LEVEL_LABELS[problem.level]}
                        </Badge>
                        <span className="text-foreground font-medium">{problem.name}</span>
                        {problem.area ? (
                            <span className="text-muted text-sm">{problem.area}</span>
                        ) : null}
                    </div>
                    <ul className="mt-2 space-y-1 text-sm">
                        {problem.reasons.map((reason) => (
                            <li key={reason.id} className="text-foreground break-words">
                                {reason.detail}
                            </li>
                        ))}
                    </ul>
                </div>
                <span className="text-muted text-xs whitespace-nowrap">
                    с {formatMoment(problem.first_seen)}
                </span>
            </div>
        </Card>
    );
}
