"use client";

import Link from "next/link";
import { Fragment, useMemo, useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sparkline } from "@/components/ui/sparkline";
import { kindLabel, roleLabel } from "@/lib/labels";
import { relativeTime } from "@/lib/time";
import type { LocationSnapshot, Reading } from "@/lib/types";

/** Колонки, по которым можно сортировать. */
type SortKey = "name" | "kind" | "temperature" | "humidity" | "motion";

/** Графики показываются только там, где есть числовая история. */
const SPARK_ROLE: Record<string, "temperature" | "humidity"> = {
    temperature: "temperature",
    humidity: "humidity",
};

/**
 * Дата-грид локаций: показания дома одной таблицей (спека 017, US1).
 *
 * Карточки хороши для трёх локаций, но не для дома целиком: чтобы сравнить
 * комнаты по температуре или найти ту, где молчат датчики, нужны строки и
 * колонки. Как и «Автоматика» — с поиском, фильтрами, сортировкой и группировкой.
 *
 * @param props Снимки локаций из агрегата «Дом».
 * @returns Панель фильтров и таблицу локаций.
 */
export function LocationGrid({ locations }: { locations: LocationSnapshot[] }) {
    const [query, setQuery] = useState("");
    const [kind, setKind] = useState("");
    const [problemsOnly, setProblemsOnly] = useState(false);
    const [group, setGroup] = useState<"none" | "kind">("kind");
    const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
        key: "name",
        dir: "asc",
    });

    const kinds = useMemo(
        () => Array.from(new Set(locations.map((l) => l.location.kind))).sort(),
        [locations],
    );

    const filtered = useMemo(() => {
        const needle = query.trim().toLowerCase();
        return locations.filter((snapshot) => {
            if (kind && snapshot.location.kind !== kind) return false;
            if (problemsOnly && problems(snapshot) === 0) return false;
            if (!needle) return true;
            return (
                snapshot.location.name.toLowerCase().includes(needle) ||
                snapshot.location.id.toLowerCase().includes(needle)
            );
        });
    }, [locations, query, kind, problemsOnly]);

    const sorted = useMemo(() => {
        const direction = sort.dir === "asc" ? 1 : -1;
        return [...filtered].sort((a, b) => {
            if (sort.key === "temperature" || sort.key === "humidity") {
                const va = numeric(a, SPARK_ROLE[sort.key]) ?? -Infinity;
                const vb = numeric(b, SPARK_ROLE[sort.key]) ?? -Infinity;
                return (va - vb) * direction;
            }
            if (sort.key === "motion") {
                const va = motionAgo(a) ?? Infinity;
                const vb = motionAgo(b) ?? Infinity;
                return (va - vb) * direction;
            }
            const value = (snapshot: LocationSnapshot) =>
                sort.key === "kind" ? snapshot.location.kind : snapshot.location.name;
            return value(a).localeCompare(value(b), "ru") * direction;
        });
    }, [filtered, sort]);

    const groups = useMemo(() => {
        if (group === "none") {
            return [["", sorted]] as Array<[string, LocationSnapshot[]]>;
        }
        const map = new Map<string, LocationSnapshot[]>();
        for (const snapshot of sorted) {
            const key = snapshot.location.kind || "other";
            map.set(key, [...(map.get(key) ?? []), snapshot]);
        }
        return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0], "ru"));
    }, [sorted, group]);

    const toggleSort = (key: SortKey) =>
        setSort((previous) =>
            previous.key === key
                ? { key, dir: previous.dir === "asc" ? "desc" : "asc" }
                : { key, dir: "asc" },
        );
    const arrow = (key: SortKey) => (sort.key === key ? (sort.dir === "asc" ? " ↑" : " ↓") : "");

    return (
        <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-2">
                <label className="text-sm">
                    <span className="text-muted">Поиск</span>
                    <input
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="имя или id локации"
                        className="border-border bg-surface-2 mt-1 block w-56 rounded-md border px-2 py-1"
                    />
                </label>
                <label className="text-sm">
                    <span className="text-muted">Вид</span>
                    <select
                        aria-label="Вид"
                        value={kind}
                        onChange={(event) => setKind(event.target.value)}
                        className="border-border bg-surface-2 mt-1 block rounded-md border px-2 py-1"
                    >
                        <option value="">все</option>
                        {kinds.map((option) => (
                            <option key={option} value={option}>
                                {kindLabel(option)}
                            </option>
                        ))}
                    </select>
                </label>
                <label className="text-muted flex items-center gap-2 text-sm">
                    <input
                        type="checkbox"
                        checked={problemsOnly}
                        onChange={(event) => setProblemsOnly(event.target.checked)}
                    />
                    только с проблемами
                </label>
                <label className="text-sm">
                    <span className="text-muted">Группировка</span>
                    <select
                        aria-label="Группировка"
                        value={group}
                        onChange={(event) => setGroup(event.target.value as "none" | "kind")}
                        className="border-border bg-surface-2 mt-1 block rounded-md border px-2 py-1"
                    >
                        <option value="none">без группировки</option>
                        <option value="kind">по виду</option>
                    </select>
                </label>
                <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                        setQuery("");
                        setKind("");
                        setProblemsOnly(false);
                    }}
                >
                    Сбросить
                </Button>
                <span className="text-muted ml-auto text-xs">
                    показано {sorted.length} из {locations.length}
                </span>
            </div>

            <div className="border-border overflow-x-auto rounded-xl border">
                <table className="w-full border-collapse text-sm">
                    <thead className="bg-surface-2 text-left">
                        <tr>
                            <Header className="w-[22%] min-w-52" onClick={() => toggleSort("name")}>
                                Локация{arrow("name")}
                            </Header>
                            <Header onClick={() => toggleSort("kind")}>Вид{arrow("kind")}</Header>
                            <Header onClick={() => toggleSort("temperature")}>
                                Температура{arrow("temperature")}
                            </Header>
                            <Header onClick={() => toggleSort("humidity")}>
                                Влажность{arrow("humidity")}
                            </Header>
                            <Header onClick={() => toggleSort("motion")}>
                                Движение{arrow("motion")}
                            </Header>
                            <Header>Открыто</Header>
                            <Header>Датчики</Header>
                        </tr>
                    </thead>
                    <tbody>
                        {groups.map(([groupName, items]) => (
                            <Fragment key={`group:${groupName}`}>
                                {group !== "none" ? (
                                    <tr className="bg-surface-2/60">
                                        <td
                                            colSpan={7}
                                            className="text-muted px-3 py-1.5 text-xs font-semibold tracking-wide"
                                        >
                                            {kindLabel(groupName)} · {items.length}
                                        </td>
                                    </tr>
                                ) : null}
                                {items.map((snapshot) => (
                                    <LocationRow key={snapshot.location.id} snapshot={snapshot} />
                                ))}
                            </Fragment>
                        ))}
                        {sorted.length === 0 ? (
                            <tr>
                                <td colSpan={7} className="text-muted px-3 py-6 text-center">
                                    Ничего не найдено: измените фильтры.
                                </td>
                            </tr>
                        ) : null}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

/**
 * Строка локации: показания ролей, движение, открытые проёмы и состояние датчиков.
 *
 * @param props Снимок локации.
 * @returns Строку таблицы.
 */
function LocationRow({ snapshot }: { snapshot: LocationSnapshot }) {
    const derived = snapshot.derived ?? {};
    const contactsOpen = Array.isArray(derived.contacts_open) ? derived.contacts_open.length : 0;
    const staleCount = typeof derived.stale_count === "number" ? derived.stale_count : 0;
    const unavailable = unavailableCount(snapshot);
    const sensors = typeof derived.sensor_count === "number" ? derived.sensor_count : 0;
    const available = typeof derived.available_count === "number" ? derived.available_count : 0;
    const lastMotion = typeof derived.last_motion_at === "string" ? derived.last_motion_at : null;

    return (
        <tr className="border-border hover:bg-surface-2/40 border-b last:border-0">
            <td className="px-3 py-2">
                <Link
                    href={`/location/?id=${encodeURIComponent(snapshot.location.id)}`}
                    className="text-accent block truncate hover:underline"
                    title={snapshot.location.id}
                >
                    {snapshot.location.name}
                </Link>
                <span className="text-muted block truncate font-mono text-xs">
                    {snapshot.location.id}
                </span>
            </td>
            <td className="px-3 py-2 whitespace-nowrap">{kindLabel(snapshot.location.kind)}</td>
            <td className="px-3 py-2">
                <ReadingCell snapshot={snapshot} role="temperature" />
            </td>
            <td className="px-3 py-2">
                <ReadingCell snapshot={snapshot} role="humidity" />
            </td>
            <td className="px-3 py-2 whitespace-nowrap">
                <span className="text-muted">{lastMotion ? relativeTime(lastMotion) : "—"}</span>
                {activeDetections(snapshot).length > 0 ? (
                    <span className="ml-2 inline-flex gap-1">
                        {activeDetections(snapshot).map((detection) => (
                            <Badge key={detection.role} variant="info">
                                {detection.label}
                            </Badge>
                        ))}
                    </span>
                ) : null}
            </td>
            <td className="px-3 py-2">
                {contactsOpen > 0 ? (
                    <Badge variant="warning">{contactsOpen}</Badge>
                ) : (
                    <span className="text-muted">—</span>
                )}
            </td>
            <td className="px-3 py-2 whitespace-nowrap">
                <span className="text-muted">
                    {available}/{sensors}
                </span>
                {staleCount > 0 ? (
                    <Badge variant="neutral" className="ml-2">
                        молчит {staleCount}
                    </Badge>
                ) : null}
                {unavailable > 0 ? (
                    <Badge variant="warning" className="ml-2">
                        нет {unavailable}
                    </Badge>
                ) : null}
            </td>
        </tr>
    );
}

/**
 * Ячейка числового показания со sparkline истории.
 *
 * @param props Снимок и роль датчика.
 * @returns Значение с единицей и график.
 */
function ReadingCell({ snapshot, role }: { snapshot: LocationSnapshot; role: string }) {
    const reading = firstReading(snapshot, role);
    if (!reading) {
        return <span className="text-muted">—</span>;
    }
    if (!reading.available) {
        return <Badge variant="warning">недоступен</Badge>;
    }
    const points = snapshot.series?.[role] ?? [];

    return (
        <span className="inline-flex items-center gap-3">
            <span className="font-mono whitespace-nowrap">
                {String(reading.value)}
                {reading.unit ? ` ${reading.unit}` : ""}
            </span>
            {points.length >= 2 ? (
                <Sparkline
                    points={points}
                    unit={reading.unit}
                    tone={role === "temperature" ? "warning" : "accent"}
                />
            ) : null}
        </span>
    );
}

/**
 * Заголовок колонки с сортировкой.
 *
 * @param props Подпись, обработчик и классы.
 * @returns Ячейку заголовка.
 */
function Header({
    children,
    onClick,
    className,
}: {
    children: ReactNode;
    onClick?: () => void;
    className?: string;
}) {
    return (
        <th
            className={`border-border border-b px-3 py-2 text-xs font-semibold whitespace-nowrap ${className ?? ""}`}
        >
            {onClick ? (
                <button type="button" onClick={onClick} className="hover:text-accent">
                    {children}
                </button>
            ) : (
                children
            )}
        </th>
    );
}

/**
 * Первое показание роли.
 *
 * @param snapshot Снимок локации.
 * @param role Роль датчика.
 * @returns Показание либо ``undefined``.
 */
function firstReading(snapshot: LocationSnapshot, role: string): Reading | undefined {
    return snapshot.readings?.[role]?.[0];
}

/**
 * Числовое значение показания роли.
 *
 * @param snapshot Снимок локации.
 * @param role Роль датчика.
 * @returns Число либо ``null``.
 */
function numeric(snapshot: LocationSnapshot, role: string): number | null {
    const reading = firstReading(snapshot, role);
    if (!reading || !reading.available) {
        return null;
    }
    const value = Number(reading.value);
    return Number.isFinite(value) ? value : null;
}

/**
 * Сколько секунд назад было движение.
 *
 * @param snapshot Снимок локации.
 * @returns Секунды либо ``null``.
 */
function motionAgo(snapshot: LocationSnapshot): number | null {
    const value = snapshot.derived?.last_motion_ago_sec;
    return typeof value === "number" ? value : null;
}

/**
 * Сколько датчиков локации недоступно.
 *
 * @param snapshot Снимок локации.
 * @returns Число недоступных датчиков.
 */
function unavailableCount(snapshot: LocationSnapshot): number {
    return Object.values(snapshot.readings ?? {})
        .flat()
        .filter((reading) => !reading.available).length;
}

/**
 * Активные детекции камеры: человек / животное / машина (спека 017).
 *
 * @param snapshot Снимок локации.
 * @returns Список активных детекций с подписями.
 */
function activeDetections(snapshot: LocationSnapshot): Array<{ role: string; label: string }> {
    const roles = ["person", "animal", "vehicle"];
    return roles
        .map((role) => {
            const readings = snapshot.readings?.[role] ?? [];
            const on = readings.some(
                (reading) =>
                    reading.available &&
                    ["on", "true", "1", "detected"].includes(String(reading.value).toLowerCase()),
            );
            return on ? { role, label: roleLabel(role) } : null;
        })
        .filter((item): item is { role: string; label: string } => item !== null);
}

/**
 * Сколько проблем у локации: молчащие и недоступные датчики.
 *
 * @param snapshot Снимок локации.
 * @returns Число проблем.
 */
function problems(snapshot: LocationSnapshot): number {
    const stale =
        typeof snapshot.derived?.stale_count === "number" ? snapshot.derived.stale_count : 0;
    return stale + unavailableCount(snapshot);
}
