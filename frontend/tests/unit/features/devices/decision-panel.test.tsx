import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DecisionPanel } from "@/features/devices/decision-panel";

describe("DecisionPanel", () => {
    it("объясняет решение человеческим языком с относительным временем", () => {
        render(
            <DecisionPanel
                decision={{
                    at: new Date(Date.now() - 180_000).toISOString(),
                    outcome: "on",
                    reason_code: "action_on",
                    reason_text: "включила по движению",
                    trigger: "motion_detected",
                }}
            />,
        );

        expect(screen.getByText("включила")).toBeInTheDocument();
        expect(screen.getByText("включила по движению")).toBeInTheDocument();
        expect(screen.getByText(/назад/)).toBeInTheDocument();
        expect(screen.getByText(/motion_detected/)).toBeInTheDocument();
    });

    it("честно сообщает, что решений не было", () => {
        render(<DecisionPanel decision={null} />);

        expect(screen.getByText(/ещё не принимала решений/)).toBeInTheDocument();
    });
});
