import {
    Activity,
    CircleAlert,
    DoorClosed,
    DoorOpen,
    Power,
    PowerOff,
    type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { StatePresentation } from "@/lib/labels";

const ICONS: Record<StatePresentation["icon"], LucideIcon> = {
    on: Power,
    off: PowerOff,
    open: DoorOpen,
    closed: DoorClosed,
    motion: Activity,
    unknown: CircleAlert,
};

const TONES: Record<StatePresentation["variant"], string> = {
    success: "text-success",
    neutral: "text-muted",
    warning: "text-warning",
    info: "text-accent",
    danger: "text-danger",
};

/**
 * Состояние прибора иконкой и подписью (спека 017, US2).
 *
 * Цвет сохраняется, но состояние читается и без цвета: у «включено» и
 * «выключено», «открыто» и «закрыто» разные иконки.
 *
 * @param props Подпись, вариант и вид иконки.
 * @returns Значок состояния.
 */
export function StateChip({ presentation }: { presentation: StatePresentation }) {
    const Icon = ICONS[presentation.icon];
    return (
        <span
            className={cn("inline-flex shrink-0 items-center gap-1.5", TONES[presentation.variant])}
            title={presentation.label}
        >
            <Icon className="size-4" aria-hidden />
            <span className="text-foreground text-sm">{presentation.label}</span>
        </span>
    );
}
