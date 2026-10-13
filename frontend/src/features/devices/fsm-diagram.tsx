"use client";

import { useEffect, useId, useRef, useState } from "react";

import { identityHeaders } from "@/lib/api";

/**
 * Схема автомата устройства (спека 017, US4, FR-022).
 *
 * Mermaid-схему отдаёт платформа готовой строкой; здесь она рисуется, а
 * текущее состояние подсвечивается, чтобы схема отвечала «где мы сейчас», а не
 * была картинкой из документации.
 *
 * @param props Сущность устройства и текущее состояние автомата.
 * @returns Схема либо честное сообщение, что она недоступна.
 */
export function FsmDiagram({
    entityId,
    currentState,
}: {
    entityId: string;
    currentState?: string;
}) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [error, setError] = useState<string | null>(null);
    const [version, setVersion] = useState(0);
    const renderId = `fsm${useId().replace(/[^a-zA-Z0-9]/g, "")}`;

    useEffect(() => {
        let cancelled = false;

        void (async () => {
            try {
                const headers = await identityHeaders();
                const response = await fetch(`/api/fsm/${encodeURIComponent(entityId)}/diagram`, {
                    headers,
                });
                if (!response.ok) {
                    if (!cancelled) {
                        setError("Схема для этого устройства не построена");
                    }
                    return;
                }
                const text = await response.text();
                const mermaid = (await import("mermaid")).default;
                mermaid.initialize({
                    startOnLoad: false,
                    theme: "dark",
                    securityLevel: "strict",
                    flowchart: { htmlLabels: false },
                });
                const { svg } = await mermaid.render(renderId, text);
                if (cancelled || !containerRef.current) {
                    return;
                }
                containerRef.current.innerHTML = svg;
                setError(null);
                setVersion((value) => value + 1);
            } catch {
                if (!cancelled) {
                    setError("Не удалось построить схему");
                }
            }
        })();

        return () => {
            cancelled = true;
        };
    }, [entityId, renderId]);

    useEffect(() => {
        const root = containerRef.current;
        if (!root) {
            return;
        }
        root.querySelectorAll(".node").forEach((node) => {
            const label = (node.textContent ?? "").trim();
            node.classList.toggle("fsm-current", Boolean(currentState) && label === currentState);
        });
    }, [currentState, version]);

    if (error) {
        return <p className="text-muted text-sm">{error}</p>;
    }

    return (
        <div
            ref={containerRef}
            data-testid="fsm-diagram"
            className="overflow-x-auto [&_svg]:mx-auto [&_svg]:max-w-full"
        />
    );
}
