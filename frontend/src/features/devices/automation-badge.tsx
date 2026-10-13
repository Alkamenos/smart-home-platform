"use client";

import { Badge } from "@/components/ui/badge";
import type { CommandResponse } from "@/lib/types";

/**
 * Признак того, учла ли автоматика ручную команду (спека 017, FR-016).
 *
 * @param props Результат последней команды.
 * @returns Бейдж либо ничего, пока команда не отправлялась.
 */
export function AutomationBadge({ result }: { result?: CommandResponse }) {
    if (!result) {
        return null;
    }
    return result.automation_synced ? (
        <Badge variant="success">автоматика учла</Badge>
    ) : (
        <Badge variant="warning">команда напрямую</Badge>
    );
}
