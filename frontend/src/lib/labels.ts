/**
 * Человекочитаемые названия и подписи (спека 017, FR-003, US4).
 *
 * Интерфейс говорит по-русски: роли датчиков, виды зон, типы приборов и
 * состояния показываются словами, а служебные идентификаторы остаются
 * второстепенной информацией.
 */

import { relativeTime } from "@/lib/time";

/** Роли датчиков локации. */
export const ROLE_LABELS: Record<string, string> = {
    temperature: "температура",
    humidity: "влажность",
    motion: "движение",
    contact: "контакт",
    illuminance: "освещённость",
    lux: "освещённость",
    pressure: "давление",
    wind: "ветер",
    rain: "дождь",
    uv: "УФ-излучение",
    co2: "CO₂",
    soil_moisture: "влага почвы",
    soil_conductivity: "проводимость почвы",
    soil_ec: "проводимость почвы",
    soil_temperature: "температура почвы",
    battery: "батарея",
    power: "мощность",
    person: "человек",
    animal: "животное",
    vehicle: "машина",
};

/**
 * Назвать роль датчика по-русски.
 *
 * @param role Роль из снимка локации.
 * @returns Человекочитаемое название.
 */
export function roleLabel(role: string): string {
    return ROLE_LABELS[role] ?? role;
}

/** Виды локаций. */
export const KIND_LABELS: Record<string, string> = {
    room: "комната",
    outdoor: "улица",
    garden: "грядки",
    other: "зона",
};

/**
 * Назвать вид локации по-русски.
 *
 * @param kind Вид из снимка.
 * @returns Человекочитаемое название.
 */
export function kindLabel(kind: string): string {
    return KIND_LABELS[kind] ?? kind;
}

/** Типы приборов Home Assistant. */
export const DEVICE_TYPE_LABELS: Record<string, string> = {
    light: "свет",
    switch: "выключатель",
    fan: "вентиляция",
    cover: "штора",
    climate: "климат",
    sensor: "датчик",
    binary_sensor: "датчик",
    media_player: "медиа",
    input_boolean: "переключатель",
    input_number: "число",
    input_select: "выбор",
    scene: "сцена",
    script: "сценарий",
    automation: "автоматизация",
    camera: "камера",
    lock: "замок",
    vacuum: "пылесос",
    humidifier: "увлажнитель",
    water_heater: "бойлер",
    update: "обновление",
    number: "число",
    select: "выбор",
    button: "кнопка",
    person: "человек",
    device_tracker: "устройство",
    sun: "солнце",
    weather: "погода",
    group: "группа",
    remote: "пульт",
};

/**
 * Назвать тип прибора по-русски.
 *
 * @param type Домен или тип из Home Assistant.
 * @returns Человекочитаемое название.
 */
export function deviceTypeLabel(type: string): string {
    return DEVICE_TYPE_LABELS[type] ?? type;
}

/** Представление состояния прибора для интерфейса. */
export interface StatePresentation {
    label: string;
    variant: "success" | "neutral" | "warning" | "info" | "danger";
    /** Имя иконки для визуального состояния. */
    icon: "on" | "off" | "open" | "closed" | "motion" | "unknown";
}

const DEVICE_STATES: Record<string, StatePresentation> = {
    on: { label: "включено", variant: "success", icon: "on" },
    off: { label: "выключено", variant: "neutral", icon: "off" },
    open: { label: "открыто", variant: "info", icon: "open" },
    closed: { label: "закрыто", variant: "neutral", icon: "closed" },
    opening: { label: "открывается", variant: "info", icon: "open" },
    closing: { label: "закрывается", variant: "info", icon: "closed" },
    home: { label: "дома", variant: "info", icon: "on" },
    not_home: { label: "нет дома", variant: "neutral", icon: "off" },
    playing: { label: "играет", variant: "success", icon: "on" },
    paused: { label: "пауза", variant: "neutral", icon: "off" },
    heating: { label: "греет", variant: "warning", icon: "on" },
    cooling: { label: "охлаждает", variant: "info", icon: "on" },
    idle: { label: "ожидает", variant: "neutral", icon: "off" },
    detected: { label: "движение", variant: "info", icon: "motion" },
    clear: { label: "тихо", variant: "neutral", icon: "off" },
};

/**
 * Представить фактическое состояние прибора.
 *
 * @param state Сырое состояние из Home Assistant.
 * @param status Доступность прибора.
 * @returns Подпись, вариант и иконка.
 */
export function deviceState(state: unknown, status: string): StatePresentation {
    if (status && status !== "available") {
        return {
            label: status === "unavailable" ? "недоступен" : status,
            variant: "warning",
            icon: "unknown",
        };
    }
    const key = String(state ?? "").toLowerCase();
    return (
        DEVICE_STATES[key] ?? {
            label: key ? key : "нет данных",
            variant: "neutral",
            icon: "unknown",
        }
    );
}

/**
 * Показать значение показания с единицей измерения.
 *
 * @param value Значение.
 * @param unit Единица измерения.
 * @returns Строка вида «22.4 °C».
 */
export function readingValue(value: unknown, unit: string | null): string {
    const text = value === null || value === undefined ? "" : String(value);
    return unit ? `${text} ${unit}` : text;
}

/** Исходы решений автоматики. */
export const DECISION_LABELS: Record<string, string> = {
    on: "включила",
    off: "выключила",
    denied: "отказала",
    none: "без команды",
};

/**
 * Назвать исход решения по-русски.
 *
 * @param outcome Исход из решения движка.
 * @returns Человекочитаемое название.
 */
export function decisionLabel(outcome: string): string {
    return DECISION_LABELS[outcome] ?? outcome;
}

/** Состояния автомата FSM в подписи для интерфейса. */
export const FSM_STATE_LABELS: Record<string, string> = {
    OFF: "выключено",
    ON: "включено",
    IDLE: "ожидает",
    HEATING: "греет",
    COOLING: "охлаждает",
    SUPPLY: "приток",
    EXHAUST: "вытяжка",
    AIRING: "проветривание",
    RECUPERATION: "рекуперация",
    OPEN: "открыто",
    CLOSED: "закрыто",
    NIGHT: "ночь",
    DAY: "день",
};

/**
 * Назвать состояние автомата по-русски.
 *
 * @param state Значение состояния из движка.
 * @returns Человекочитаемая подпись.
 */
export function fsmStateLabel(state: string): string {
    return FSM_STATE_LABELS[state] ?? state;
}

export { relativeTime };
