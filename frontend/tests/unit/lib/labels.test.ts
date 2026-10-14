import { describe, expect, it } from "vitest";

import { deviceState, deviceTypeLabel, kindLabel, readingValue, roleLabel } from "@/lib/labels";

describe("labels", () => {
    it("называет роли и виды по-русски", () => {
        expect(roleLabel("temperature")).toBe("температура");
        expect(roleLabel("unknown_role")).toBe("unknown_role");
        expect(kindLabel("outdoor")).toBe("улица");
    });

    it("склеивает значение с единицей", () => {
        expect(readingValue(22.4, "°C")).toBe("22.4 °C");
        expect(readingValue("on", null)).toBe("on");
    });

    it("показывает недоступный прибор, а не последнее состояние", () => {
        expect(deviceState("on", "unavailable")).toEqual({
            label: "недоступен",
            variant: "warning",
            icon: "unknown",
        });
    });

    it("переводит известное состояние прибора", () => {
        expect(deviceState("on", "available")).toEqual({
            label: "включено",
            variant: "success",
            icon: "on",
        });
    });

    it("неизвестное состояние показывает как есть, а не молча прячет", () => {
        expect(deviceState("heating", "available")).toMatchObject({ label: "греет" });
        expect(deviceState("нечто", "available")).toMatchObject({ label: "нечто" });
    });

    it("называет тип прибора по-русски", () => {
        expect(deviceTypeLabel("light")).toBe("свет");
        expect(deviceTypeLabel("cover")).toBe("штора");
        expect(deviceTypeLabel("weird")).toBe("weird");
    });
});
