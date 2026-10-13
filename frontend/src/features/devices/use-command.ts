"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { CommandResponse, DeviceDetail, Overview } from "@/lib/types";

/** Команды, отражаемые на карточке мгновенно. */
const OPTIMISTIC_STATE: Record<string, string> = {
    turn_on: "on",
    turn_off: "off",
};

export interface CommandInput {
    deviceId: string;
    entityId: string;
    name: string;
    parameters?: Record<string, unknown>;
}

/**
 * Управление прибором с мгновенным откликом (спека 017, US2, FR-013…FR-016).
 *
 * Состояние на карточке меняется сразу (оптимистично), пока команда идёт к
 * прибору; при неудаче изменение откатывается, и причина показывается
 * пользователю. Это устраняет «тормоза»: интерфейс не ждёт ответа Home Assistant.
 *
 * @returns Мутация команды: `mutate`, `isPending`, `data`, `error`.
 */
export function useDeviceCommand() {
    const queryClient = useQueryClient();

    return useMutation<CommandResponse, Error, CommandInput, { previous?: Overview }>({
        mutationFn: ({ deviceId, name, parameters }) =>
            apiFetch<CommandResponse>(`/api/v1/devices/${deviceId}/command`, {
                method: "POST",
                body: JSON.stringify({ name, parameters: parameters ?? {} }),
            }),
        onMutate: async ({ entityId, name }) => {
            await queryClient.cancelQueries({ queryKey: ["overview"] });
            const previous = queryClient.getQueryData<Overview>(["overview"]);
            const expected = OPTIMISTIC_STATE[name];
            if (previous && expected) {
                queryClient.setQueryData<Overview>(["overview"], {
                    ...previous,
                    devices: previous.devices.map((device) =>
                        device.ha_entity_id === entityId
                            ? { ...device, state: { ...device.state, state: expected } }
                            : device,
                    ),
                });
            }
            return { previous };
        },
        onError: (_error, _variables, context) => {
            if (context?.previous) {
                queryClient.setQueryData(["overview"], context.previous);
            }
        },
        onSettled: (_data, _error, variables) => {
            void queryClient.invalidateQueries({ queryKey: ["overview"] });
            void queryClient.invalidateQueries({ queryKey: ["device", variables.deviceId] });
        },
    });
}

/**
 * Обновить состояние устройства в кэше детальной страницы.
 *
 * @param queryClient Кэш запросов.
 * @param deviceId Идентификатор устройства.
 */
export function invalidateDevice(
    queryClient: ReturnType<typeof useQueryClient>,
    deviceId: string,
): void {
    void queryClient.invalidateQueries({ queryKey: ["device", deviceId] });
    void queryClient.invalidateQueries({ queryKey: ["deviceDetail", deviceId] });
}

export type { DeviceDetail };
