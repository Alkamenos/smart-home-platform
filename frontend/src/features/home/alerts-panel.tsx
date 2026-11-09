import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardTitle } from "@/components/ui/card";
import type { Alert } from "@/lib/types";

/**
 * Панель тревог: то, что требует внимания (спека 017, FR-011).
 *
 * @param props Список тревог.
 * @returns Панель тревог или спокойную строку.
 */
export function AlertsPanel({ alerts }: { alerts: Alert[] }) {
    return (
        <Card data-testid="alerts-panel">
            <div className="mb-3 flex items-center justify-between">
                <CardTitle>Требует внимания</CardTitle>
                {alerts.length > 0 ? <Badge variant="warning">{alerts.length}</Badge> : null}
            </div>
            {alerts.length === 0 ? (
                <p className="text-muted text-sm">Отклонений нет.</p>
            ) : (
                <ul className="space-y-2">
                    {alerts.map((alert) => (
                        <li
                            key={`${alert.kind}:${alert.subject}:${alert.at ?? ""}`}
                            className="flex items-start gap-2 text-sm"
                        >
                            <Badge
                                variant={
                                    alert.level === "critical"
                                        ? "danger"
                                        : alert.severity === "warning"
                                          ? "warning"
                                          : "neutral"
                                }
                            >
                                {alert.level === "critical"
                                    ? "CRIT"
                                    : alert.severity === "warning"
                                      ? "WARN"
                                      : "INFO"}
                            </Badge>
                            <span className="text-foreground min-w-0 break-words">
                                {alert.detail}
                            </span>
                        </li>
                    ))}
                </ul>
            )}
            {alerts.length > 0 ? (
                <Link className="text-muted mt-3 inline-block text-xs underline" href="/problems/">
                    Все проблемы дома
                </Link>
            ) : null}
        </Card>
    );
}
