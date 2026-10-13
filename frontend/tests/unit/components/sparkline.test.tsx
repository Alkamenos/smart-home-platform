import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Sparkline } from "@/components/ui/sparkline";

const POINTS = [
    { at: "2026-10-13T09:00:00Z", value: 22.0 },
    { at: "2026-10-13T10:00:00Z", value: 22.4 },
    { at: "2026-10-13T11:00:00Z", value: 23.1 },
];

describe("Sparkline", () => {
    it("не показывает подписи min/max справа", () => {
        const { container } = render(<Sparkline points={POINTS} unit="°C" />);

        expect(container.textContent).toBe("");
        expect(container.querySelector("polyline")).toBeTruthy();
    });

    it("при наведении показывает значение и время точки", () => {
        render(<Sparkline points={POINTS} unit="°C" />);

        const svg = screen.getByRole("img");
        // Ширина в jsdom нулевая — компонент берёт базовые 96 px: середина = вторая точка.
        fireEvent.mouseMove(svg, { clientX: 48 });

        expect(screen.getByText(/22\.4 °C · \d{2}:\d{2}/)).toBeInTheDocument();
    });

    it("прячет подсказку, когда курсор ушёл", () => {
        render(<Sparkline points={POINTS} unit="°C" />);

        const svg = screen.getByRole("img");
        fireEvent.mouseMove(svg, { clientX: 48 });
        expect(screen.getByText(/22\.4 °C/)).toBeInTheDocument();

        fireEvent.mouseLeave(svg);
        expect(screen.queryByText(/22\.4 °C/)).not.toBeInTheDocument();
    });

    it("честно пишет, что истории нет", () => {
        render(<Sparkline points={[{ at: "2026-10-13T09:00:00Z", value: 22 }]} />);

        expect(screen.getByText("нет истории")).toBeInTheDocument();
    });
});
