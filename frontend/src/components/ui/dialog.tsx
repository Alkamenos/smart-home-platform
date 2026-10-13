"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Надёжный диалог на Radix (спека 017, US5, FR-006).
 *
 * Заменяет хрупкую связку htmx + Bootstrap-modal старого интерфейса, из-за
 * которой модальные окна переставали открываться: у Radix открытие, фокус,
 * закрытие по Esc и возврат фокуса — часть самого примитива, а не ручная
 * синхронизация атрибутов.
 */
export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;

/**
 * Содержимое диалога.
 *
 * @param props Заголовок, описание, содержимое и классы.
 * @returns Окно диалога.
 */
export function DialogContent({
    title,
    description,
    children,
    className,
}: {
    title: string;
    description?: string;
    children: ReactNode;
    className?: string;
}) {
    return (
        <DialogPrimitive.Portal>
            <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/60" />
            <DialogPrimitive.Content
                data-testid="dialog-content"
                className={cn(
                    "border-border bg-surface fixed top-1/2 left-1/2 z-50 w-[min(92vw,32rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl border p-5 shadow-lg",
                    className,
                )}
            >
                <div className="mb-3 flex items-start justify-between gap-4">
                    <div>
                        <DialogPrimitive.Title className="text-base font-semibold">
                            {title}
                        </DialogPrimitive.Title>
                        {description ? (
                            <DialogPrimitive.Description className="text-muted mt-1 text-sm">
                                {description}
                            </DialogPrimitive.Description>
                        ) : null}
                    </div>
                    <DialogPrimitive.Close
                        aria-label="Закрыть"
                        className="text-muted hover:text-foreground"
                    >
                        <X className="size-4" />
                    </DialogPrimitive.Close>
                </div>
                {children}
            </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
    );
}
