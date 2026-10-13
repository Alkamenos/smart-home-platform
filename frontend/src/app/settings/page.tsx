import Link from "next/link";

import { Card, CardTitle } from "@/components/ui/card";

/** Подразделы настроек: каждый решает одну работу (спека 017, US5). */
const SECTIONS = [
    {
        href: "/settings/sources/",
        title: "Источники",
        description: "Подключить Home Assistant, проверить сущности, импортировать устройства.",
    },
    {
        href: "/settings/devices/",
        title: "Устройства",
        description: "Поведения и параметры, права доступа к прибору.",
    },
    {
        href: "/settings/locations/",
        title: "Локации",
        description: "Комнаты и зоны: какие роли датчиков к ним привязаны.",
    },
    {
        href: "/settings/manifest/",
        title: "Манифест",
        description: "Правка конфигурации дома с проверкой и ошибками по полям.",
    },
];

/**
 * Раздел «Настройка»: хаб подразделов.
 *
 * @returns Хаб настроек.
 */
export default function SettingsPage() {
    return (
        <div className="space-y-4">
            <h1 className="text-xl font-semibold">Настройка</h1>
            <div className="grid gap-3 sm:grid-cols-2">
                {SECTIONS.map((section) => (
                    <Link
                        key={section.href}
                        href={section.href}
                        className="focus-visible:ring-accent rounded-xl outline-none focus-visible:ring-2"
                    >
                        <Card className="h-full">
                            <CardTitle>{section.title}</CardTitle>
                            <p className="text-muted mt-2 text-sm">{section.description}</p>
                        </Card>
                    </Link>
                ))}
            </div>
        </div>
    );
}
