import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Слить классы Tailwind, разрешая конфликты в пользу последнего.
 *
 * @param inputs Классы и условные выражения.
 * @returns Итоговая строка классов.
 */
export function cn(...inputs: ClassValue[]): string {
    return twMerge(clsx(inputs));
}
