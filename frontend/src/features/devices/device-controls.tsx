"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { CommandResponse } from "@/lib/types";

import { AutomationBadge } from "@/features/devices/automation-badge";
import { useDeviceCommand } from "@/features/devices/use-command";

/** Домены приборов, которыми можно управлять включением/выключением. */
const SWITCHABLE_DOMAINS = ["light", "switch", "fan", "input_boolean"];

/**
 * Управление прибором: включить/выключить с мгновенным откликом (US2).
 *
 * @param props Идентификаторы прибора и его текущее состояние.
 * @returns Кнопка управления и признаки результата.
 */
export function DeviceControls({
    deviceId,
    entityId,
    isOn,
}: {
    deviceId: string;
    entityId: string;
    isOn: boolean;
}) {
    const mutation = useDeviceCommand();
    const [last, setLast] = useState<CommandResponse | undefined>(undefined);

    const domain = entityId.split(".")[0];
    if (!SWITCHABLE_DOMAINS.includes(domain)) {
        return null;
    }

    const command = isOn ? "turn_off" : "turn_on";

    return (
        <div className="flex flex-wrap items-center gap-2">
            <Button
                size="sm"
                variant="outline"
                disabled={mutation.isPending}
                onClick={() =>
                    mutation.mutate(
                        { deviceId, entityId, name: command },
                        { onSuccess: (result) => setLast(result) },
                    )
                }
            >
                {mutation.isPending ? "Выполняется…" : isOn ? "Выключить" : "Включить"}
            </Button>
            <AutomationBadge result={last} />
            {mutation.error ? (
                <span className="text-danger text-xs">{mutation.error.message}</span>
            ) : null}
        </div>
    );
}
