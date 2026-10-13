"use client";

import { Lock, Unlock, Wifi, WifiOff } from "lucide-react";
import Link from "next/link";
import { Fragment, useMemo, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { StateChip } from "@/components/ui/state-chip";
import { deviceState, deviceTypeLabel, fsmStateLabel } from "@/lib/labels";
import type { Device } from "@/lib/types";

import { useOverrides } from "@/features/devices/use-overrides";

/** Колонки, по которым можно сортировать. */
type SortKey = "name" | "room_name" | "device_type" | "state" | "status";

/** Вид группировки. */
type GroupKey = "none" | "room_name" | "device_type";

/**
 * Дата-грид приборов: поиск, фильтры, сортировка и группировка (спека 017, US2).
 *
 * Карточки не годятся для 20+ приборов: нужное не найти. Грид отвечает на
 * «покажи все лампы на террасе» и «что сейчас недоступно» за один взгляд.
 *
 * @param props Приборы из агрегата «Дом».
 * @returns Панель фильтров и таблица.
 */
export function DeviceGrid({ devices }: { devices: Device[] }) {
    const { overrides, release } = useOverrides();
    const locked = useMemo(() => {
        const map = new Map(overrides.map((item) => [item.entity_id, item]));
        return map;
    }, [overrides]);

    const [query, setQuery] = useState("");
    const [room, setRoom] = useState("");
    const [type, setType] = useState("");
    const [status, setStatus] = useState("");
    const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
        key: "name",
        dir: "asc",
    });
    const [group, setGroup] = useState<GroupKey>("room_name");

    const rooms = useMemo(
        () =>
            Array.from(new Set(devices.map((d) => d.room_name).filter(Boolean))).sort() as string[],
        [devices],
    );
    const types = useMemo(
        () => Array.from(new Set(devices.map((d) => d.device_type).filter(Boolean))).sort(),
        [devices],
    );

    const filtered = useMemo(() => {
        const needle = query.trim().toLowerCase();
        return devices.filter((device) => {
            if (room && device.room_name !== room) return false;
            if (type && device.device_type !== type) return false;
            if (status === "available" && device.status !== "available") return false;
            if (status === "unavailable" && device.status === "available") return false;
            if (!needle) return true;
            return (
                device.name.toLowerCase().includes(needle) ||
                device.ha_entity_id.toLowerCase().includes(needle) ||
                (device.room_name ?? "").toLowerCase().includes(needle)
            );
        });
    }, [devices, query, room, type, status]);

    const sorted = useMemo(() => {
        const direction = sort.dir === "asc" ? 1 : -1;
        return [...filtered].sort((a, b) => {
            const value = (device: Device) => {
                if (sort.key === "state") return stateText(device);
                return String(device[sort.key] ?? "");
            };
            return value(a).localeCompare(value(b), "ru") * direction;
        });
    }, [filtered, sort]);

    const groups = useMemo(() => {
        if (group === "none") {
            return [["", sorted]] as Array<[string, Device[]]>;
        }
        const map = new Map<string, Device[]>();
        for (const device of sorted) {
            const key = (device[group] as string | null) ?? "— без группы —";
            map.set(key, [...(map.get(key) ?? []), device]);
        }
        return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0], "ru"));
    }, [sorted, group]);

    const toggleSort = (key: SortKey) => {
        setSort((previous) =>
            previous.key === key
                ? { key, dir: previous.dir === "asc" ? "desc" : "asc" }
                : { key, dir: "asc" },
        );
    };
    const arrow = (key: SortKey) => (sort.key === key ? (sort.dir === "asc" ? " ↑" : " ↓") : "");

    return (
        <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-2">
                <label className="text-sm">
                    <span className="text-muted">Поиск</span>
                    <input
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="имя, сущность или комната"
                        className="border-border bg-surface-2 mt-1 block w-64 rounded-md border px-2 py-1"
                    />
                </label>
                <Select label="Комната" value={room} onChange={setRoom} options={rooms} />
                <Select
                    label="Тип"
                    value={type}
                    onChange={setType}
                    options={types}
                    render={(value) => deviceTypeLabel(value)}
                />
                <label className="text-sm">
                    <span className="text-muted">Доступность</span>
                    <select
                        aria-label="Доступность"
                        value={status}
                        onChange={(event) => setStatus(event.target.value)}
                        className="border-border bg-surface-2 mt-1 block rounded-md border px-2 py-1"
                    >
                        <option value="">все</option>
                        <option value="available">доступны</option>
                        <option value="unavailable">недоступны</option>
                    </select>
                </label>
                <label className="text-sm">
                    <span className="text-muted">Группировка</span>
                    <select
                        aria-label="Группировка"
                        value={group}
                        onChange={(event) => setGroup(event.target.value as GroupKey)}
                        className="border-border bg-surface-2 mt-1 block rounded-md border px-2 py-1"
                    >
                        <option value="none">без группировки</option>
                        <option value="room_name">по комнате</option>
                        <option value="device_type">по типу</option>
                    </select>
                </label>
                <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                        setQuery("");
                        setRoom("");
                        setType("");
                        setStatus("");
                    }}
                >
                    Сбросить
                </Button>
                <span className="text-muted ml-auto text-xs">
                    показано {sorted.length} из {devices.length}
                </span>
            </div>

            <div className="border-border overflow-x-auto rounded-xl border">
                <table className="w-full border-collapse text-sm">
                    <thead className="bg-surface-2 text-left">
                        <tr>
                            <Header className="w-[28%] min-w-64" onClick={() => toggleSort("name")}>
                                Прибор{arrow("name")}
                            </Header>
                            <Header onClick={() => toggleSort("room_name")}>
                                Комната{arrow("room_name")}
                            </Header>
                            <Header onClick={() => toggleSort("device_type")}>
                                Тип{arrow("device_type")}
                            </Header>
                            <Header onClick={() => toggleSort("state")}>
                                Состояние{arrow("state")}
                            </Header>
                            <Header onClick={() => toggleSort("status")}>
                                Связь{arrow("status")}
                            </Header>
                            <Header>Автоматика</Header>
                            <Header>Блокировка</Header>
                        </tr>
                    </thead>
                    <tbody>
                        {groups.map(([groupName, groupDevices]) => (
                            <Fragment key={`group:${groupName}`}>
                                {group !== "none" ? (
                                    <tr className="bg-surface-2/60">
                                        <td
                                            colSpan={7}
                                            className="text-muted px-3 py-1.5 text-xs font-semibold tracking-wide"
                                        >
                                            {group === "device_type"
                                                ? deviceTypeLabel(groupName)
                                                : groupName}{" "}
                                            · {groupDevices.length}
                                        </td>
                                    </tr>
                                ) : null}
                                {groupDevices.map((device) => (
                                    <DeviceRow
                                        key={device.id}
                                        device={device}
                                        lockedUntil={locked.get(device.ha_entity_id)?.expires_at}
                                        onRelease={() => release.mutate(device.ha_entity_id)}
                                        releasing={release.isPending}
                                    />
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
 * Строка прибора.
 *
 * @param props Прибор, срок блокировки и обработчик снятия.
 * @returns Строку таблицы.
 */
function DeviceRow({
    device,
    lockedUntil,
    onRelease,
    releasing,
}: {
    device: Device;
    lockedUntil?: number;
    onRelease: () => void;
    releasing: boolean;
}) {
    const presentation = deviceState(rawState(device), device.status);
    const available = device.status === "available";

    return (
        <tr className="border-border hover:bg-surface-2/40 border-b last:border-0">
            <td className="px-3 py-2">
                <Link
                    href={`/device/?id=${encodeURIComponent(device.id)}`}
                    className="text-accent block truncate hover:underline"
                    title={device.ha_entity_id}
                >
                    {device.name || device.ha_entity_id}
                </Link>
                <span className="text-muted block truncate font-mono text-xs">
                    {device.ha_entity_id}
                </span>
            </td>
            <td className="px-3 py-2 whitespace-nowrap">{device.room_name ?? "—"}</td>
            <td className="px-3 py-2 whitespace-nowrap">{deviceTypeLabel(device.device_type)}</td>
            <td className="px-3 py-2">
                <StateChip presentation={presentation} />
            </td>
            <td className="px-3 py-2">
                {available ? (
                    <Wifi className="text-success size-4" aria-label="доступен" />
                ) : (
                    <WifiOff className="text-warning size-4" aria-label="недоступен" />
                )}
            </td>
            <td className="px-3 py-2">
                {device.fsm?.length ? (
                    <span className="flex flex-wrap gap-1">
                        {device.fsm.map((state) => (
                            <span
                                key={state.fsm_id}
                                className="border-border bg-surface-2 inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs whitespace-nowrap"
                                title={`шаблон: ${state.behavior}`}
                            >
                                <span className="text-muted">{state.behavior}</span>
                                <span>{fsmStateLabel(state.state)}</span>
                            </span>
                        ))}
                    </span>
                ) : (
                    <span className="text-muted">нет</span>
                )}
            </td>
            <td className="px-3 py-2">
                {lockedUntil ? (
                    <span className="flex items-center gap-2 whitespace-nowrap">
                        <Lock className="text-warning size-4" aria-label="заблокировано" />
                        <span className="text-muted text-xs">
                            {new Date(lockedUntil * 1000).toLocaleTimeString("ru-RU", {
                                hour: "2-digit",
                                minute: "2-digit",
                            })}
                        </span>
                        <Button size="sm" variant="ghost" disabled={releasing} onClick={onRelease}>
                            <Unlock className="size-4" /> Снять
                        </Button>
                    </span>
                ) : (
                    <span className="text-muted">—</span>
                )}
            </td>
        </tr>
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
 * Выпадающий фильтр.
 *
 * @param props Подпись, значение, обработчик, варианты и формат подписи.
 * @returns Поле выбора.
 */
function Select({
    label,
    value,
    onChange,
    options,
    render,
}: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    options: string[];
    render?: (value: string) => string;
}) {
    return (
        <label className="text-sm">
            <span className="text-muted">{label}</span>
            <select
                aria-label={label}
                value={value}
                onChange={(event) => onChange(event.target.value)}
                className="border-border bg-surface-2 mt-1 block rounded-md border px-2 py-1"
            >
                <option value="">все</option>
                {options.map((option) => (
                    <option key={option} value={option}>
                        {render ? render(option) : option}
                    </option>
                ))}
            </select>
        </label>
    );
}

/**
 * Сырое состояние прибора.
 *
 * @param device Прибор.
 * @returns Значение состояния.
 */
function rawState(device: Device): unknown {
    return device.state && typeof device.state === "object" ? device.state.state : device.state;
}

/**
 * Человекочитаемая подпись состояния для сортировки.
 *
 * @param device Прибор.
 * @returns Подпись состояния.
 */
function stateText(device: Device): string {
    return deviceState(rawState(device), device.status).label;
}
