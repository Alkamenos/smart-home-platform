import { describe, expect, it } from "vitest";

import { validateSource } from "@/features/settings/source-validation";

describe("validateSource", () => {
    it("принимает корректные данные", () => {
        const errors = validateSource({
            name: "Home Assistant",
            url: "http://192.168.1.10:8123",
            token: "very-long-token",
        });

        expect(errors).toEqual({});
    });

    it("требует название", () => {
        const errors = validateSource({ name: "  ", url: "http://h", token: "long-token-1" });

        expect(errors.name).toBeTruthy();
    });

    it("требует http-адрес", () => {
        const errors = validateSource({ name: "HA", url: "192.168.1.10", token: "long-token-1" });

        expect(errors.url).toMatch(/http/);
    });

    it("требует достаточно длинный токен", () => {
        const errors = validateSource({ name: "HA", url: "http://h", token: "short" });

        expect(errors.token).toBeTruthy();
    });
});
