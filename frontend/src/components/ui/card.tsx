import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Поверхность-карточка раздела.
 *
 * @param props Свойства элемента div.
 * @returns Карточка.
 */
export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
    return (
        <div
            className={cn("border-border bg-surface rounded-xl border p-4 shadow-sm", className)}
            {...props}
        />
    );
}

/**
 * Заголовок карточки.
 *
 * @param props Свойства элемента.
 * @returns Заголовок.
 */
export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
    return <h3 className={cn("text-sm font-semibold tracking-wide", className)} {...props} />;
}
