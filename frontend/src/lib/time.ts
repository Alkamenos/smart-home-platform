import dayjs from "dayjs";
import relativeTimePlugin from "dayjs/plugin/relativeTime";
import "dayjs/locale/ru";

dayjs.extend(relativeTimePlugin);
dayjs.locale("ru");

/**
 * Относительное время по-русски (спека 017, US3): «сейчас», «5 мин назад»,
 * «3 мес назад». Считается локально через dayjs с русской локализацией — единый
 * источник для страниц, чтобы формулировки не расходились.
 *
 * @param iso Время в формате ISO-8601.
 * @returns Человекочитаемое «сколько назад».
 */
export function relativeTime(iso: string | null): string {
    if (!iso) {
        return "нет данных";
    }
    const moment = dayjs(iso);
    if (!moment.isValid()) {
        return "нет данных";
    }
    return moment.fromNow();
}

/**
 * Время суток в локальной зоне.
 *
 * @param iso Время в формате ISO-8601.
 * @returns Строка вида «14:05».
 */
export function clockTime(iso: string | null): string {
    if (!iso) {
        return "—";
    }
    const moment = dayjs(iso);
    return moment.isValid() ? moment.format("HH:mm") : "—";
}

/**
 * Дата и время в локальной зоне.
 *
 * @param iso Время в формате ISO-8601.
 * @returns Строка вида «13.10.2026 14:05».
 */
export function dateTime(iso: string | null): string {
    if (!iso) {
        return "—";
    }
    const moment = dayjs(iso);
    return moment.isValid() ? moment.format("DD.MM.YYYY HH:mm") : "—";
}

export { dayjs };
