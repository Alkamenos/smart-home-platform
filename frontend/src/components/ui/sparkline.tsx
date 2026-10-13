"use client";

import { useState } from "react";

import { clockTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import type { SeriesPoint } from "@/lib/types";

const WIDTH = 96;
const HEIGHT = 28;

/**
 * Мини-график истории показаний (спека 017, US1).
 *
 * Рисуется встроенным SVG: тянуть библиотеку графиков ради линии из десятка
 * точек не нужно. Подписи min/max справа нет — значение и время показываются
 * при наведении на точку, чтобы не загромождать строку таблицы.
 *
 * @param props Точки (время и значение), единица измерения и цвет.
 * @returns Sparkline либо прочерк, если данных мало.
 */
export function Sparkline({
    points,
    unit,
    className,
    tone = "accent",
}: {
    points: SeriesPoint[];
    unit?: string | null;
    className?: string;
    tone?: "accent" | "success" | "warning";
}) {
    const [hover, setHover] = useState<number | null>(null);

    if (!points || points.length < 2) {
        return <span className={cn("text-muted text-xs", className)}>нет истории</span>;
    }

    const values = points.map((point) => point.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const step = WIDTH / (points.length - 1);
    const coords = values.map((value, index) => {
        const x = index * step;
        const y = HEIGHT - ((value - min) / span) * (HEIGHT - 4) - 2;
        return { x, y };
    });

    const stroke = {
        accent: "var(--color-accent)",
        success: "var(--color-success)",
        warning: "var(--color-warning)",
    }[tone];

    const active = hover === null ? null : points[hover];
    const activeCoord = hover === null ? null : coords[hover];

    return (
        <span className={cn("relative inline-flex", className)}>
            <svg
                width={WIDTH}
                height={HEIGHT}
                viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
                role="img"
                aria-label={`История: от ${min} до ${max}${unit ? ` ${unit}` : ""}`}
                className="overflow-visible"
                onMouseLeave={() => setHover(null)}
                onMouseMove={(event) => {
                    const rect = event.currentTarget.getBoundingClientRect();
                    const offset = event.clientX - rect.left;
                    const index = Math.round(
                        offset / ((rect.width || WIDTH) / (points.length - 1)),
                    );
                    setHover(Math.min(points.length - 1, Math.max(0, index)));
                }}
            >
                <polyline
                    points={coords
                        .map((coord) => `${coord.x.toFixed(1)},${coord.y.toFixed(1)}`)
                        .join(" ")}
                    fill="none"
                    stroke={stroke}
                    strokeWidth="1.5"
                    strokeLinejoin="round"
                    strokeLinecap="round"
                />
                {activeCoord ? (
                    <circle cx={activeCoord.x} cy={activeCoord.y} r="2.5" fill={stroke} />
                ) : null}
            </svg>

            {active && activeCoord ? (
                <span
                    className="border-border bg-surface-2 pointer-events-none absolute -top-8 z-10 rounded-md border px-2 py-1 font-mono text-xs whitespace-nowrap"
                    style={{
                        left: `${(activeCoord.x / WIDTH) * 100}%`,
                        transform: "translateX(-50%)",
                    }}
                >
                    {active.value}
                    {unit ? ` ${unit}` : ""} · {clockTime(active.at)}
                </span>
            ) : null}
        </span>
    );
}
