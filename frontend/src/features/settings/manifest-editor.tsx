"use client";

import { autocompletion, type Completion, type CompletionContext } from "@codemirror/autocomplete";
import { json, jsonParseLinter } from "@codemirror/lang-json";
import { lintGutter, linter, type Diagnostic } from "@codemirror/lint";
import { useQuery } from "@tanstack/react-query";
import CodeMirror from "@uiw/react-codemirror";
import Ajv, { type ErrorObject, type ValidateFunction } from "ajv";
import { useMemo } from "react";

import { apiFetch } from "@/lib/api";

/** Справочник автокомплита из платформы. */
export interface ManifestHints {
    roles: string[];
    templates: string[];
    entities: Array<{ id: string; name: string }>;
}

/** Ключи, значение которых — сущность Home Assistant. */
const ENTITY_KEYS = new Set(["id", "entity_id", "feature_entity", "my_doma_entity"]);

/**
 * Собрать имена ключей из JSON Schema (рекурсивно).
 *
 * Схема — источник истины о структуре: подсказка ключей не разойдётся с моделью.
 *
 * @param schema JSON Schema.
 * @returns Отсортированный список имён свойств.
 */
export function schemaKeys(schema: unknown): string[] {
    const found = new Set<string>();
    const walk = (node: unknown, depth: number) => {
        if (depth > 6 || typeof node !== "object" || node === null) {
            return;
        }
        const record = node as Record<string, unknown>;
        const properties = record.properties;
        if (properties && typeof properties === "object") {
            for (const [key, value] of Object.entries(properties as Record<string, unknown>)) {
                found.add(key);
                walk(value, depth + 1);
            }
        }
        for (const key of ["items", "additionalProperties", "anyOf", "oneOf", "allOf"]) {
            const child = record[key];
            if (Array.isArray(child)) {
                child.forEach((item) => walk(item, depth + 1));
            } else {
                walk(child, depth + 1);
            }
        }
    };
    walk(schema, 0);
    return [...found].sort();
}

/**
 * Варианты значений для ключа манифеста.
 *
 * @param key Ключ, для которого набирается значение.
 * @param hints Справочник платформы.
 * @returns Варианты подсказок.
 */
export function valueOptions(key: string, hints: ManifestHints | undefined): Completion[] {
    if (!hints) {
        return [];
    }
    if (key === "template") {
        return hints.templates.map((name) => ({ label: name, type: "enum" }));
    }
    if (key === "kind") {
        return ["room", "outdoor", "garden", "other"].map((name) => ({
            label: name,
            type: "enum",
        }));
    }
    if (hints.roles.includes(key)) {
        return hints.entities.map((entity) => ({
            label: entity.id,
            detail: entity.name,
            type: "variable",
        }));
    }
    if (ENTITY_KEYS.has(key)) {
        return hints.entities.map((entity) => ({
            label: entity.id,
            detail: entity.name,
            type: "variable",
        }));
    }
    return [];
}

/**
 * Источник автокомплита: ключи по схеме, значения — по данным платформы.
 *
 * @param schema JSON Schema манифеста.
 * @param hints Справочник платформы.
 * @returns Источник подсказок для CodeMirror.
 */
export function makeCompletionSource(schema: unknown, hints: ManifestHints | undefined) {
    const keys = schemaKeys(schema);
    return (context: CompletionContext) => {
        const line = context.state.doc.lineAt(context.pos);
        const before = line.text.slice(0, context.pos - line.from);
        // Значение: строка вида `"ключ": "нач`
        const valueMatch = /"([A-Za-z_][A-Za-z0-9_]*)"\s*:\s*"?([^"]*)$/.exec(before);
        if (valueMatch) {
            const options = valueOptions(valueMatch[1], hints);
            if (!options.length) {
                return null;
            }
            return { from: context.pos - valueMatch[2].length, options, validFor: /^[\w.-]*$/ };
        }
        // Ключ: строка вида `"нач`
        const keyMatch = /"([A-Za-z_][A-Za-z0-9_]*)?$/.exec(before);
        if (keyMatch && keys.length) {
            return {
                from: context.pos - (keyMatch[1]?.length ?? 0),
                options: keys.map((key) => ({ label: key, type: "property", apply: `${key}": ` })),
                validFor: /^[\w]*$/,
            };
        }
        return null;
    };
}

/**
 * Диагностика схемы: где в тексте находится ошибочный путь.
 *
 * @param text Текст документа.
 * @param error Ошибка ajv.
 * @returns Позиция и сообщение для CodeMirror.
 */
export function diagnosticFromError(
    text: string,
    error: ErrorObject,
): { from: number; to: number; message: string; severity: "error" } {
    const segments = String(error.instancePath || "")
        .split("/")
        .filter(Boolean);
    const last = segments[segments.length - 1] ?? "";
    let at = 0;
    if (last) {
        const index = text.lastIndexOf(`"${last}"`);
        at = index >= 0 ? index : 0;
    }
    const to = Math.min(text.length, at + Math.max(last.length + 2, 1));
    return {
        from: at,
        to,
        severity: "error",
        message: `${error.instancePath || "манифест"}: ${error.message ?? "некорректное значение"}`,
    };
}

/**
 * Редактор манифеста: подсветка, проверка по схеме, автокомплит (спека 017).
 *
 * Серверная проверка остаётся источником истины; редактор лишь показывает ошибку
 * до сохранения — по той же схеме, которой платформа валидирует манифест.
 *
 * @param props Значение и обработчик изменения.
 * @returns Редактор CodeMirror.
 */
export function ManifestEditor({
    value,
    onChange,
}: {
    value: string;
    onChange: (value: string) => void;
}) {
    const schema = useQuery({
        queryKey: ["manifestSchema"],
        queryFn: () => apiFetch<Record<string, unknown>>("/api/v1/manifest/schema"),
        staleTime: Infinity,
    });
    const hints = useQuery({
        queryKey: ["manifestHints"],
        queryFn: () => apiFetch<ManifestHints>("/api/v1/manifest/hints"),
        staleTime: 60_000,
    });

    const validate: ValidateFunction | null = useMemo(() => {
        if (!schema.data) {
            return null;
        }
        try {
            return new Ajv({ allErrors: true, strict: false }).compile(schema.data);
        } catch {
            return null;
        }
    }, [schema.data]);

    const schemaLinter = useMemo(
        () =>
            linter((view): Diagnostic[] => {
                if (!validate) {
                    return [];
                }
                const text = view.state.doc.toString();
                let parsed: unknown;
                try {
                    parsed = JSON.parse(text);
                } catch {
                    return []; // о разборе сообщит jsonParseLinter
                }
                if (validate(parsed)) {
                    return [];
                }
                return (validate.errors ?? []).map((error) => diagnosticFromError(text, error));
            }),
        [validate],
    );

    const completion = useMemo(
        () => autocompletion({ override: [makeCompletionSource(schema.data, hints.data)] }),
        [schema.data, hints.data],
    );

    return (
        <CodeMirror
            value={value}
            height="30rem"
            theme="dark"
            basicSetup={{ foldGutter: true, lineNumbers: true }}
            extensions={[json(), linter(jsonParseLinter()), lintGutter(), schemaLinter, completion]}
            onChange={onChange}
        />
    );
}
