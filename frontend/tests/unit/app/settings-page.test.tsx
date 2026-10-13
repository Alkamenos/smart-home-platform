import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
    default: ({ children, ...props }: { children: ReactNode }) => <a {...props}>{children}</a>,
}));

import SettingsPage from "@/app/settings/page";

describe("SettingsPage", () => {
    it("ведёт в четыре подраздела", () => {
        render(<SettingsPage />);

        expect(screen.getByRole("link", { name: /Источники/ })).toHaveAttribute(
            "href",
            "/settings/sources/",
        );
        expect(screen.getByRole("link", { name: /Устройства/ })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /Локации/ })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /Манифест/ })).toBeInTheDocument();
    });
});
