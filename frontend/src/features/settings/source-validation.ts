/**
 * Проверка формы источника Home Assistant (спека 017, US5, FR-024).
 *
 * Ошибки проверяются до отправки: «неверный адрес» видно сразу, а не после
 * отказа сервера, и ошибка привязана к полю, а не к форме целиком.
 */

import { z } from "zod";

/** Схема формы нового источника. */
export const sourceSchema = z.object({
    name: z.string().trim().min(1, "укажите название"),
    url: z
        .string()
        .trim()
        .min(1, "укажите адрес")
        .refine(
            (value) => /^https?:\/\/\S+$/i.test(value),
            "адрес должен начинаться с http:// или https://",
        ),
    token: z.string().trim().min(10, "токен слишком короткий"),
});

export type SourceInput = z.infer<typeof sourceSchema>;

/** Ошибки полей формы. */
export type FieldErrors = Partial<Record<keyof SourceInput, string>>;

/**
 * Проверить данные формы источника.
 *
 * @param input Значения полей формы.
 * @returns Ошибки по полям; пустой объект, если всё верно.
 */
export function validateSource(input: Partial<SourceInput>): FieldErrors {
    const result = sourceSchema.safeParse({
        name: input.name ?? "",
        url: input.url ?? "",
        token: input.token ?? "",
    });
    if (result.success) {
        return {};
    }
    const errors: FieldErrors = {};
    for (const issue of result.error.issues) {
        const field = issue.path[0] as keyof SourceInput | undefined;
        if (field && !errors[field]) {
            errors[field] = issue.message;
        }
    }
    return errors;
}
