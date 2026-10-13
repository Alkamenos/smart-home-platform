"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/** Разделы: каждый решает одну работу инженера (спека 017, FR-001). */
const SECTIONS = [
    { href: "/", label: "Дом", hint: "Что сейчас и что не так" },
    { href: "/devices/", label: "Автоматика", hint: "Устройства, решения, управление" },
    { href: "/journal/", label: "Журнал", hint: "Следствие: события и трассировка" },
    { href: "/settings/", label: "Настройка", hint: "Источники, устройства, локации" },
    { href: "/system/", label: "Система", hint: "Готовность, метрики, логи" },
];

/**
 * Верхняя навигация: единая для всех разделов (FR-002).
 *
 * @returns Панель навигации.
 */
export function TopNav() {
    const pathname = usePathname();

    return (
        <header className="border-border bg-background/95 sticky top-0 z-20 border-b backdrop-blur">
            <nav
                aria-label="Разделы"
                className="mx-auto flex max-w-6xl flex-wrap items-center gap-1 px-4 py-3"
            >
                <span className="text-foreground mr-4 text-sm font-semibold tracking-wide">
                    Дом
                    <span className="text-muted ml-2">пульт инженера</span>
                </span>
                {SECTIONS.map((section) => {
                    const active =
                        section.href === "/" ? pathname === "/" : pathname.startsWith(section.href);
                    return (
                        <Link
                            key={section.href}
                            href={section.href}
                            title={section.hint}
                            aria-current={active ? "page" : undefined}
                            className={cn(
                                "rounded-md px-3 py-1.5 text-sm transition-colors",
                                active
                                    ? "bg-surface-2 text-foreground"
                                    : "text-muted hover:bg-surface-2 hover:text-foreground",
                            )}
                        >
                            {section.label}
                        </Link>
                    );
                })}
            </nav>
        </header>
    );
}
