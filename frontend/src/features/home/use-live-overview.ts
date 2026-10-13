"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { EventStream, type StateChangeMessage } from "@/lib/ws";

/**
 * Живые обновления первого экрана (спека 017, FR-012).
 *
 * На изменение состояния сущности обновляет агрегат «Дом»: показания локаций
 * меняются без перезагрузки. Само соединение живёт в объекте потока и
 * переподключается само.
 *
 * @returns Признак того, что канал открыт.
 */
export function useLiveOverview(): boolean {
    const queryClient = useQueryClient();
    const [connected, setConnected] = useState(false);

    useEffect(() => {
        const stream = new EventStream();
        const unsubscribe = stream.onMessage((message) => {
            if (message.type === "state_change") {
                const change = message as StateChangeMessage;
                void queryClient.invalidateQueries({ queryKey: ["overview"] });
                return change;
            }
            if (message.type === "authenticated" || message.type === "subscribed") {
                setConnected(true);
            }
        });
        stream.start();
        return () => {
            unsubscribe();
            stream.stop();
            setConnected(false);
        };
    }, [queryClient]);

    return connected;
}
