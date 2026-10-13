import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
    default: ({ children, ...props }: { children: ReactNode }) => <a {...props}>{children}</a>,
}));

import { LocationGrid } from "@/features/home/location-grid";
import type { LocationSnapshot, Reading } from "@/lib/types";

function reading(value: string, unit: string | null, overrides: Partial<Reading> = {}): Reading {
    return {
        value,
        unit,
        at: new Date(Date.now() - 60_000).toISOString(),
        stale: false,
        available: true,
        entity_id: `sensor.${value}`,
        ...overrides,
    };
}

function location(
    overrides: Partial<LocationSnapshot> & { id?: string; name?: string; kind?: string },
): LocationSnapshot {
    const { id = "spalnia", name = "Спальня", kind = "room", ...rest } = overrides;
    return {
        location: { id, name, kind },
        at: new Date().toISOString(),
        available: true,
        readings: {},
        derived: {},
        ...rest,
    };
}

const LOCATIONS: LocationSnapshot[] = [
    location({
        id: "spalnia",
        name: "Спальня",
        readings: { temperature: [reading("23.9", "°C")] },
        series: {
            temperature: [
                { at: "", value: 23.5 },
                { at: "", value: 23.9 },
            ],
        },
        derived: {
            last_motion_at: new Date(Date.now() - 300_000).toISOString(),
            sensor_count: 1,
            available_count: 1,
        },
    }),
    location({
        id: "gostinaia",
        name: "Гостиная",
        readings: { temperature: [reading("25.6", "°C")], humidity: [reading("40", "%")] },
        derived: { sensor_count: 2, available_count: 2 },
    }),
    location({
        id: "griadki",
        name: "Грядки",
        kind: "garden",
        readings: {
            temperature: [reading("0", "°C", { available: false, entity_id: "sensor.soil" })],
        },
        derived: { sensor_count: 1, available_count: 0, stale_count: 1 },
    }),
];

describe("LocationGrid", () => {
    it("показывает локации с показаниями и видом по-русски", () => {
        render(<LocationGrid locations={LOCATIONS} />);

        expect(screen.getByText("Спальня")).toBeInTheDocument();
        expect(screen.getByText("23.9 °C")).toBeInTheDocument();
        expect(screen.getByText("25.6 °C")).toBeInTheDocument();
        expect(screen.getByText("40 %")).toBeInTheDocument();
        expect(screen.getAllByText("комната").length).toBeGreaterThan(0);
        expect(screen.getByText(/показано 3 из 3/)).toBeInTheDocument();
    });

    it("показывает движение относительным временем", () => {
        render(<LocationGrid locations={LOCATIONS} />);

        expect(screen.getByText(/назад/)).toBeInTheDocument();
    });

    it("отмечает недоступный датчик", () => {
        render(<LocationGrid locations={LOCATIONS} />);

        expect(screen.getByText("недоступен")).toBeInTheDocument();
        expect(screen.getByText("нет 1")).toBeInTheDocument();
        expect(screen.getByText("молчит 1")).toBeInTheDocument();
    });

    it("ищет по имени", async () => {
        render(<LocationGrid locations={LOCATIONS} />);

        await userEvent.type(screen.getByPlaceholderText(/имя или id/i), "гостин");

        expect(screen.getByText("Гостиная")).toBeInTheDocument();
        expect(screen.queryByText("Спальня")).not.toBeInTheDocument();
    });

    it("фильтрует локации с проблемами", async () => {
        render(<LocationGrid locations={LOCATIONS} />);

        await userEvent.click(screen.getByLabelText(/только с проблемами/i));

        expect(screen.getByText("Грядки")).toBeInTheDocument();
        expect(screen.queryByText("Спальня")).not.toBeInTheDocument();
    });

    it("группирует по виду", () => {
        render(<LocationGrid locations={LOCATIONS} />);

        expect(screen.getByText(/комната · 2/)).toBeInTheDocument();
        expect(screen.getByText(/грядки · 1/)).toBeInTheDocument();
    });

    it("сортирует по температуре", async () => {
        render(<LocationGrid locations={LOCATIONS} />);
        await userEvent.selectOptions(screen.getByLabelText("Группировка"), "none");

        await userEvent.click(screen.getByRole("button", { name: /Температура/ }));

        const rows = screen.getAllByRole("row").slice(1);
        // Возрастание: сначала «нет данных» (Грядки), затем Спальня (23.9), затем Гостиная (25.6).
        expect(within(rows[0]).getByText("Грядки")).toBeInTheDocument();
        expect(within(rows[1]).getByText("Спальня")).toBeInTheDocument();
        expect(within(rows[2]).getByText("Гостиная")).toBeInTheDocument();
    });
});
