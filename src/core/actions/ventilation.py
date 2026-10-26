"""Действия вентиляции: вентиляторы, проветривание и вытяжка."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from loguru import logger

from core.actions.common import extract_device_id
from core.commands.dispatcher import CommandIntent


def _fan_intent(
    context: dict[str, Any],
    service: str,
    source: str,
    keys: tuple[str, ...] = (),
    skip_if: dict[str, Any] | None = None,
) -> CommandIntent | None:
    """Собрать команду вентилятора.

    ``keys`` перечисляет поля, которые **разрешено** положить в данные команды
    именно этой услуги. Собирать все известные поля подряд нельзя: у сервисов
    Home Assistant строгая схема, и лишний ключ роняет команду целиком — HA
    отвечает ``400 Bad Request``. Так ``fan.set_preset_mode`` с подмешанным
    ``percentage`` не применялся вовсе, и рекуператор оставался в прежнем режиме,
    пока платформа считала, что переключила его (боевой разбор 2026-10-12).

    Args:
        context: Контекст перехода.
        service: Услуга Home Assistant.
        source: Источник для аудита и блокировок.
        keys: Поля контекста, допустимые в данных этой услуги.
        skip_if: Состояние и атрибуты прибора, при которых команда не нужна:
            у боевого рекуператора от каждой команды вспыхивает дисплей
            (замечание владельца 2026-10-19), а повтор «того же режима» ничего
            не меняет.

    Returns:
        CommandIntent либо ``None``, если устройство не указано.
    """
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning(f"{source}: нет entity_id в контексте")
        return None

    data: dict[str, Any] = {key: context[key] for key in keys if context.get(key) is not None}

    logger.info(f"Создаю команду {service} для {entity_id}, данные: {data}")

    return CommandIntent(
        device_id=entity_id,
        domain="fan",
        service=service,
        data=data,
        priority=context.get("priority", 50),
        source=source,
        skip_if=skip_if,
    )


def fan_turn_on(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить вентилятор.

    Args:
        state: Текущее состояние автомата (не используется).
        context: Контекст с ``entity_id`` и, необязательно, ``percentage``.

    Returns:
        Команда включения либо ``None`` без устройства.
    """
    percentage = context.get("percentage")
    skip_if: dict[str, Any] = {"state": "on"}
    if percentage is not None:
        skip_if["percentage"] = percentage
    return _fan_intent(context, "turn_on", "fan_turn_on", keys=("percentage",), skip_if=skip_if)


def fan_turn_off(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Выключить вентилятор.

    Данных нет вовсе: ``fan.turn_off`` скорости не принимает, а лишний ключ
    (например, накопленный ``percentage``) роняет команду с 400.

    Args:
        state: Текущее состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда выключения либо ``None`` без устройства.
    """
    return _fan_intent(context, "turn_off", "fan_turn_off", skip_if={"state": "off"})


def fan_set_percentage(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Задать скорость вентилятора.

    Скорость — отдельная ось рекуператора и не зависит от режима (FR-020,
    FR-021). В данных команды лежит **ровно** ``percentage``: лишний ключ в
    команде Home Assistant отвергает с 400 Bad Request, и вместе с ним теряется
    вся команда.

    Скорость задаётся сервисом ``fan.turn_on`` с процентом, а не
    ``fan.set_percentage``: у боевого рекуператора последний врёт — на живых
    замерах 2026-10-12 запрос 14 давал 100 %, запрос 71 не применялся вовсе,
    тогда как ``fan.turn_on`` с процентом ставил нужную ступень надёжно и не
    сбивал режим (research.md D24). Оба сервиса — стандартные сервисы Home
    Assistant, ``fan.turn_on`` с ``percentage`` заодно гарантирует, что прибор
    включён (скорость у выключенного рекуператора не принимается).

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``percentage`` (0–100).

    Returns:
        Команда скорости либо ``None`` без устройства или значения.
    """
    del state
    percentage = context.get("percentage")
    if percentage is None or isinstance(percentage, bool):
        logger.warning("fan_set_percentage: нет процента скорости в контексте")
        return None
    try:
        value = int(percentage)
    except (TypeError, ValueError):
        logger.warning(f"fan_set_percentage: процент не число: {percentage!r}")
        return None
    if not 0 <= value <= 100:
        logger.warning(f"fan_set_percentage: процент {value} вне диапазона 0–100")
        return None

    return _fan_intent(
        {**context, "percentage": value},
        "turn_on",
        "fan_set_percentage",
        keys=("percentage",),
        skip_if={"state": "on", "percentage": value},
    )


def fan_set_preset(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Задать режим вентилятора.

    Режим выбирается из списка самого устройства (``research.md`` D7):
    «Приток», «Рекуперация (зима)» и другие. Платформа физику не считает — она
    выбирает то, что умеет прибор.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``preset_mode``.

    Returns:
        Команда режима либо ``None`` без устройства или названия режима.
    """
    del state
    preset_mode = context.get("preset_mode") or context.get("chosen_mode")
    if not isinstance(preset_mode, str) or not preset_mode.strip():
        logger.warning("fan_set_preset: нет названия режима в контексте")
        return None

    return _fan_intent(
        {**context, "preset_mode": preset_mode},
        "set_preset_mode",
        "fan_set_preset",
        keys=("preset_mode",),
        skip_if={"state": "on", "preset_mode": preset_mode},
    )


def fan_airing_on(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Включить проветривание: режим максимального притока (``mode_airing``).

    Отдельное действие, а не общий ``fan_set_preset``: имя режима проветривания
    лежит в собственном параметре ``mode_airing``, и подставлять его в условие
    было бы нельзя — условие не меняет контекст, а действие его не сохраняет
    между переходами. Иначе переиспользованное имя режима пережило бы
    проветривание и следующий переход поставил бы «Приток MAX» вместо обычного
    режима (боевой урок: состояние накопительное, research.md D17).

    Действие для ВХОДА в ``AIRING``: прибор мог быть выключен, поэтому он ещё и
    включается. Подтверждение уже работающего прибора — ``fan_airing_reassert``.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``mode_airing``.

    Returns:
        Шаги: включение прибора, затем режим максимального притока.
    """
    del state
    mode = context.get("mode_airing")
    if not isinstance(mode, str) or not mode.strip():
        logger.warning("fan_airing_on: нет режима проветривания (mode_airing) в контексте")
        return []
    # Прибор может быть выключен (владелец выключал вентиляцию, рекуператор
    # остался off): одного режима мало — прибор надо ещё и включить. Включение
    # уходит с процентом 100: без него интеграция меняет атрибуты, но прибор не
    # запускает. И идёт оно ПЕРВЫМ, а режим — последним: включение с процентом
    # сбрасывает режим прибора на базовый, поэтому «последнее слово» должно быть
    # за режимом (боевой разбор 2026-10-13: прибор возвращался в «Рекуперацию»
    # через пару минут после нашей пары команд).
    power = _fan_intent(
        {**context, "percentage": 100},
        "turn_on",
        "fan_airing_on",
        keys=("percentage",),
        skip_if={"state": "on", "percentage": 100},
    )
    preset = _fan_intent(
        {**context, "preset_mode": mode},
        "set_preset_mode",
        "fan_airing_on",
        keys=("preset_mode",),
        skip_if={"state": "on", "preset_mode": mode},
    )
    return [step for step in (power, preset) if step is not None]


def fan_airing_reassert(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Подтвердить режим максимального притока, НЕ трогая включение.

    Нужно в состоянии ``AIRING``: прибор уже работает, и его надо лишь удержать
    на «Притоке MAX». Включение с процентом здесь нельзя — прибор обрабатывает
    его с задержкой и переключается на базовый режим, «соскакивая» с максимума
    (боевой разбор 2026-10-13: через 17 секунд после подтверждения прибор снова
    стоял на «Рекуперации (зиме)»). Сам «Приток MAX» форсирует 100, поэтому
    скорости не нужно.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``mode_airing``.

    Returns:
        Команда режима либо ``None`` без устройства или названия режима.
    """
    del state
    mode = context.get("mode_airing")
    if not isinstance(mode, str) or not mode.strip():
        logger.warning("fan_airing_reassert: нет режима проветривания (mode_airing) в контексте")
        return None
    return _fan_intent(
        {**context, "preset_mode": mode},
        "set_preset_mode",
        "fan_airing_reassert",
        keys=("preset_mode",),
        skip_if={"state": "on", "preset_mode": mode},
    )


def fan_apply_mode_and_speed(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Задать режим и скорость — двумя независимыми командами.

    У рекуператора это две независимые оси (FR-021), и смена скорости не должна
    сбрасывать режим. Одной командой обе не задать: у сервисов Home Assistant
    нет общего вызова, а значит порядок — «режим, затем скорость».

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``, ``preset_mode`` и ``percentage``.

    Returns:
        Два шага: режим, затем скорость.
    """
    del state
    mode_step = fan_set_preset(None, context)
    speed_step = fan_set_percentage(None, context)
    return [step for step in (mode_step, speed_step) if step is not None]


def exhaust_on(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить вытяжку.

    Вытяжка санузла — прибор без скорости: только вкл/выкл (``research.md``,
    таблица устройств). Команда уходит без данных: ``turn_on`` сервису ничего
    не нужно, а лишний ключ отвергается с 400 Bad Request.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда либо ``None`` без устройства.
    """
    del state
    return _fan_intent(context, "turn_on", "exhaust_on", skip_if={"state": "on"})


def exhaust_off(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Выключить вытяжку.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда либо ``None`` без устройства.
    """
    del state
    return _fan_intent(context, "turn_off", "exhaust_off", skip_if={"state": "off"})


def _modifier_off_intent(
    context: dict[str, Any], entity_key: str, source: str
) -> CommandIntent | None:
    """Собрать команду снятия модификатора владельца (``input_boolean.turn_off``).

    Модификаторы «проветривание» и «вытяжка» выключаются только в Home
    Assistant: у платформы нет своего хранилища желаний владельца. Сущность
    берётся из доменных правил дома (``automation_rules.ventilation``), которые
    фабрика кладёт в параметры поведения: ``airing_entity`` для проветривания,
    ``exhaust_entity`` для вытяжки.

    ``input_boolean.turn_off`` идемпотентен: если модификатор уже снят, прибор
    не изменится.

    Args:
        context: Контекст перехода.
        entity_key: Имя ключа контекста с сущностью модификатора.
        source: Источник для аудита.

    Returns:
        Команда записи либо ``None``, если сущность не задана.
    """
    entity_id = context.get(entity_key)
    if not isinstance(entity_id, str) or not entity_id:
        logger.warning(f"{source}: нет сущности модификатора ({entity_key}) в контексте")
        return None

    logger.info(f"Создаю команду input_boolean.turn_off для {entity_id} ({source})")
    return CommandIntent(
        device_id=entity_id,
        domain="input_boolean",
        service="turn_off",
        data={},
        priority=context.get("priority", 50),
        source=source,
    )


def airing_after_timeout(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Проветривание кончилось: вернуть обычный режим и снять модификатор.

    У перехода ровно одно действие (конституция I), поэтому «вернуть обычный
    режим» и «снять модификатор» — список шагов одного действия. Снятие
    модификатора идёт **последним**: обычный режим должен встать до того, как
    Home Assistant пришлёт событие ``airing_on = false`` и состояние
    пересчитается (FR-024, FR-025, T085).

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``preset_mode``/``percentage`` и ``airing_entity``.

    Returns:
        Шаги: обычный режим и скорость, затем снятие модификатора.
    """
    del state
    steps: list[CommandIntent] = list(fan_apply_mode_and_speed(None, context))
    reset = _modifier_off_intent(context, "airing_entity", "airing_reset")
    if reset is not None:
        steps.append(reset)
    return steps


def exhaust_after_timeout(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Вытяжка по модификатору кончилась: погасить прибор и снять модификатор.

    Если вытяжку включил сам санузел (температура или влажность), следующее
    событие датчика включит её снова — модификатор здесь ни при чём. Снятие
    модификатора убирает ручную причину, а не единственную (T085, T086).

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` вытяжки и ``exhaust_entity``.

    Returns:
        Шаги: выключение вытяжки, затем снятие модификатора.
    """
    del state
    steps: list[CommandIntent] = []
    off = exhaust_off(None, context)
    if off is not None:
        steps.append(off)
    reset = _modifier_off_intent(context, "exhaust_entity", "exhaust_reset")
    if reset is not None:
        steps.append(reset)
    return steps


def airing_off(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Прервать проветривание: погасить вентиляцию и снять модификатор.

    Запасной путь таймера: обычный режим вернуть нельзя (нет улицы, работает
    обогрев, выключил владелец), поэтому прибор гасится, а модификатор
    снимается — иначе проветривание продлилось бы само на следующем показании
    датчика.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``airing_entity``.

    Returns:
        Шаги: выключение вентиляции, затем снятие модификатора.
    """
    del state
    steps: list[CommandIntent] = []
    off = fan_turn_off(None, context)
    if off is not None:
        steps.append(off)
    reset = _modifier_off_intent(context, "airing_entity", "airing_reset")
    if reset is not None:
        steps.append(reset)
    return steps
