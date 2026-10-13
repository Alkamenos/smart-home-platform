import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TopNav } from "@/features/shell/top-nav";

vi.mock("next/navigation", () => ({
    usePathname: () => "/",
}));

describe("TopNav", () => {
    it("показывает пять разделов", () => {
        render(<TopNav />);

        for (const label of ["Дом", "Автоматика", "Журнал", "Настройка", "Система"]) {
            expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
        }
    });

    it("отмечает активный раздел", () => {
        render(<TopNav />);

        expect(screen.getByRole("link", { name: "Дом" })).toHaveAttribute("aria-current", "page");
    });
});
