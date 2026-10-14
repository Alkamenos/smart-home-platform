import { describe, expect, it } from "vitest";

import {
    diagnosticFromError,
    makeCompletionSource,
    schemaKeys,
    valueOptions,
    type ManifestHints,
} from "@/features/settings/manifest-editor";

const SCHEMA = {
    type: "object",
    properties: {
        instance: {
            type: "object",
            properties: { id: { type: "string" }, name: { type: "string" } },
        },
        rooms: {
            type: "array",
            items: {
                type: "object",
                properties: {
                    id: { type: "string" },
                    sensors: { type: "object", additionalProperties: { type: "string" } },
                    devices: {
                        type: "array",
                        items: { type: "object", properties: { id: { type: "string" } } },
                    },
                },
            },
        },
    },
};

const HINTS: ManifestHints = {
    roles: ["temperature", "humidity", "person"],
    templates: ["lighting", "cover_modes"],
    entities: [
        { id: "sensor.t_spalnia", name: "Спальня температура" },
        { id: "light.girlianda", name: "Гирлянда" },
    ],
};

describe("schemaKeys", () => {
    it("собирает ключи из вложенной схемы, включая массивы", () => {
        const keys = schemaKeys(SCHEMA);

        for (const key of ["instance", "id", "name", "rooms", "sensors", "devices"]) {
            expect(keys).toContain(key);
        }
    });
});

describe("valueOptions", () => {
    it("для template предлагает имена шаблонов", () => {
        expect(valueOptions("template", HINTS).map((option) => option.label)).toEqual([
            "lighting",
            "cover_modes",
        ]);
    });

    it("для роли предлагает сущности", () => {
        const options = valueOptions("temperature", HINTS);
        expect(options.map((option) => option.label)).toContain("sensor.t_spalnia");
    });

    it("для id предлагает сущности", () => {
        expect(valueOptions("id", HINTS).map((option) => option.label)).toContain(
            "light.girlianda",
        );
    });

    it("для kind предлагает вид зоны", () => {
        expect(valueOptions("kind", HINTS).map((option) => option.label)).toEqual([
            "room",
            "outdoor",
            "garden",
            "other",
        ]);
    });

    it("без справочника ничего не предлагает", () => {
        expect(valueOptions("template", undefined)).toEqual([]);
    });
});

describe("makeCompletionSource", () => {
    function context(text: string) {
        return {
            pos: text.length,
            state: { doc: { lineAt: () => ({ from: 0, text }) } },
        } as never;
    }

    it("подсказывает значения ключа по набранному префиксу", () => {
        const source = makeCompletionSource(SCHEMA, HINTS);
        const result = source(context('"template": "lig'));

        expect(result).not.toBeNull();
        expect(result?.options.map((option) => option.label)).toContain("lighting");
    });

    it("подсказывает ключи манифеста", () => {
        const source = makeCompletionSource(SCHEMA, HINTS);
        const result = source(context('"inst'));

        expect(result?.options.map((option) => option.label)).toContain("instance");
    });
});

describe("diagnosticFromError", () => {
    it("указывает место ошибочного поля в тексте", () => {
        const text = '{\n  "instance": {\n    "id": 5\n  }\n}';
        const diagnostic = diagnosticFromError(text, {
            instancePath: "/instance/id",
            message: "must be string",
        } as never);

        expect(diagnostic.severity).toBe("error");
        expect(diagnostic.message).toContain("/instance/id");
        expect(text.slice(diagnostic.from, diagnostic.to)).toContain('"id"');
    });
});
