import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AlertsPanel } from "@/features/home/alerts-panel";

describe("AlertsPanel", () => {
    it("сообщает, когда отклонений нет", () => {
        render(<AlertsPanel alerts={[]} />);

        expect(screen.getByText("Отклонений нет.")).toBeInTheDocument();
    });

    it("показывает тревогу и заметку", () => {
        render(
            <AlertsPanel
                alerts={[
                    {
                        kind: "unavailable_device",
                        subject: "fan.rekuperator",
                        severity: "warning",
                        detail: "Рекуператор: прибор unavailable",
                        at: null,
                    },
                    {
                        kind: "stale_sensor",
                        subject: "binary_sensor.window",
                        severity: "info",
                        detail: "Спальня: контакт молчит",
                        at: "2026-10-13T06:00:00Z",
                    },
                ]}
            />,
        );

        expect(screen.getByText("WARN")).toBeInTheDocument();
        expect(screen.getByText("INFO")).toBeInTheDocument();
        expect(screen.getByText("Рекуператор: прибор unavailable")).toBeInTheDocument();
    });
});
