"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { clockTime } from "@/lib/time";
import type { JournalRecord } from "@/lib/types";

import { useEntityNames } from "@/features/journal/use-entity-names";

/** Тона для значений состояний в журнале. */
const STATE_TONES: Record<string, string> = {
    on: "text-success",
    off: "text-muted",
    open: "text-accent",
    opened: "text-accent",
    closed: "text-muted",
    detected: "text-accent",
    clear: "text-muted",
    home: "text-accent",
    not_home: "text-muted",
    unavailable: "text-warning",
    unknown: "text-warning",
};

/**
 * Подсветить значение состояния (спека 017, US4).
 *
 * @param props Значение состояния.
 * @returns Цветной фрагмент.
 */
function StateValue({ value }: { value: unknown }) {
    const text = value === null || value === undefined || value === "" ? "—" : String(value);
    const tone = STATE_TONES[text.toLowerCase()] ?? "";
    return <span className={cn("font-mono", tone)}>{text}</span>;
}

/**
 * Виртуальная лента журнала (спека 017, US4, FR-020).
 *
 * Отрисовываются только видимые строки: тысяча записей листается без длинных
 * задач, в отличие от прежней страницы, которая перерисовывала список целиком.
 *
 * @param props Записи и обработчик выбора трассировки.
 * @returns Прокручиваемую ленту.
 */
export function JournalList({
    records,
    onPickTrace,
}: {
    records: JournalRecord[];
    onPickTrace?: (traceId: string) => void;
}) {
    const entityName = useEntityNames();
    const parentRef = useRef<HTMLDivElement>(null);
    // TanStack Virtual нельзя мемоизировать безопасно с React Compiler, но это
    // подходящий инструмент для длинной ленты: без него тысяча записей
    // отрисовывается целиком (FR-020). Правило отключено осознанно.
    // eslint-disable-next-line react-hooks/incompatible-library
    const virtualizer = useVirtualizer({
        count: records.length,
        getScrollElement: () => parentRef.current,
        estimateSize: () => 44,
        overscan: 8,
    });

    return (
        <div
            ref={parentRef}
            data-testid="journal-list"
            className="border-border bg-surface h-[60vh] overflow-auto rounded-xl border"
        >
            <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
                {virtualizer.getVirtualItems().map((item) => {
                    const record = records[item.index];
                    return (
                        <div
                            key={item.key}
                            data-index={item.index}
                            ref={virtualizer.measureElement}
                            style={{
                                position: "absolute",
                                top: 0,
                                left: 0,
                                width: "100%",
                                transform: `translateY(${item.start}px)`,
                            }}
                        >
                            <JournalRow
                                record={record}
                                name={entityName(record.entity_id)}
                                onPickTrace={onPickTrace}
                            />
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

/**
 * Одна запись журнала: время, имя прибора, подсвеченный переход.
 *
 * @param props Запись, имя прибора и обработчик выбора трассировки.
 * @returns Строку журнала.
 */
function JournalRow({
    record,
    name,
    onPickTrace,
}: {
    record: JournalRecord;
    name: string;
    onPickTrace?: (traceId: string) => void;
}) {
    const copyId = () => {
        void navigator.clipboard?.writeText(record.entity_id);
    };

    return (
        <div className="border-border/60 flex items-center gap-3 border-b px-3 py-2 text-sm">
            <span className="text-muted w-14 shrink-0 font-mono text-xs">
                {clockTime(record.at)}
            </span>
            <Badge variant={record.kind === "transition" ? "info" : "neutral"}>
                {record.kind === "transition" ? "автомат" : "событие"}
            </Badge>
            <button
                type="button"
                onClick={copyId}
                title={`${record.entity_id} — нажмите, чтобы скопировать`}
                className="max-w-[16rem] min-w-0 shrink-0 truncate text-left hover:underline"
            >
                {name}
            </button>
            <span className="flex min-w-0 flex-1 items-center gap-2">
                {record.title === "Переход отклонён" ? (
                    <Badge variant="warning">отклонён</Badge>
                ) : null}
                <StateValue value={record.old_value} />
                <span className="text-muted">→</span>
                <StateValue value={record.value} />
                {record.kind === "transition" && record.value === null ? (
                    <span className="text-muted truncate">{record.title}</span>
                ) : null}
            </span>
            {record.trace_id && onPickTrace ? (
                <button
                    type="button"
                    className="text-accent shrink-0 text-xs hover:underline"
                    onClick={() => onPickTrace(record.trace_id ?? "")}
                >
                    трассировка
                </button>
            ) : null}
        </div>
    );
}
