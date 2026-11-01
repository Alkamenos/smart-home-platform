"""Действия климата: кондиционер, обогреватели и уставки."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from loguru import logger

from core.actions.common import extract_device_id
from core.commands.dispatcher import CommandIntent


def _climate_intent(
    context: dict[str, Any],
    service: str,
    source: str,
    *,
    hvac_mode: str | None = None,
) -> CommandIntent | None:
    """Собрать команду климатического устройства.

    Args:
        context: Контекст перехода.
        service: Услуга Home Assistant.
        source: Источник для аудита и блокировок.
        hvac_mode: Режим кондиционера, если его нужно задать явно.

    Returns:
        CommandIntent либо ``None``, если устройство не указано.
    """
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning(f"{source}: нет entity_id в контексте")
        return None

    data: dict[str, Any] = {}
    # Имя параметра в манифесте — `target_temp`; прежнее чтение `target_temperature`
    # означало, что команда всегда уходила без температуры, сколько бы её ни задали
    # в конфигурации (#71). Старое имя оставлено как запасной вариант: им пользуются
    # вызовы вне контекста поведения.
    target_temperature = context.get("target_temp")
    if target_temperature is None:
        target_temperature = context.get("target_temperature")
    if target_temperature is not None:
        data["temperature"] = target_temperature

    # Режим кондиционера: `cool` для охлаждения, `dry` для осушения. Общая
    # ось с `set_temperature`: у кондиционера один режим на комнату, и два
    # автомата, дергающие его попеременно, выглядели бы как поломка.
    mode = hvac_mode if hvac_mode is not None else context.get("hvac_mode")
    if mode is not None and not isinstance(mode, bool):
        data["hvac_mode"] = mode

    logger.info(f"Создаю команду {service} для {entity_id}, данные: {data}")

    return CommandIntent(
        device_id=entity_id,
        domain="climate",
        service=service,
        data=data,
        priority=context.get("priority", 50),
        source=source,
        # Кондиционер, включённый зимой с пульта, выключается даже если
        # платформа считает устройство занятым: включение зимой портит технику
        # (FR-015), и блокировка тут была бы препятствием, а не защитой.
        bypass_lockout=bool(context.get("bypass_lockout", False)),
    )


def ac_dry_on(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить осушение кондиционером.

    Осушение — отдельный режим `dry` того же кондиционера, а не второй
    устройство: режим у него один, и переключение с охлаждения на осушение
    меняет ``hvac_mode`` (FR-017).

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``humidity_threshold``.

    Returns:
        Команда ``climate.set_hvac_mode`` либо ``None``.
    """
    del state
    return _climate_intent(context, "set_hvac_mode", "ac_dry_on", hvac_mode="dry")


def ac_off(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Выключить кондиционер.

    Нужен для возврата из режимов охлаждения и осушения в обогрев: пока
    кондиционер работает, обогреватель платформа включает не будет — два
    источника тепла в одной комнате.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда ``climate.turn_off`` либо ``None``.
    """
    del state
    return _climate_intent(context, "turn_off", "ac_off")


def ac_set_mode(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Переключить режим кондиционера.

    Режим меняется только при фактическом изменении потребности: у кондиционера
    сигналит при каждой смене режима (FR-016, требование владельца), поэтому
    «просто отправить на каждое показание датчика» — недопустимо.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``hvac_mode``.

    Returns:
        Команда ``climate.set_hvac_mode`` либо ``None``.
    """
    del state
    mode = context.get("hvac_mode")
    if mode is None or isinstance(mode, bool):
        logger.warning("ac_set_mode: режим не задан — переключать нечем")
        return None
    return _climate_intent(context, "set_hvac_mode", "ac_set_mode")


#: Сколько минут обогреватель работает по одному решению, если в манифесте дли��ость
#: не задана (минуты).
#:
#: Значение по умолчанию подобрано так, чтобы обогреватель успевал набрать
#: температуру, но не работал вхолостую, если датчик показывает, что уже достигнуто.
#: Каждое следующее решение принимается по свежему показанию датчика.
DEFAULT_HEATER_RUN_MINUTES = 15


def _heater_intent(
    context: dict[str, Any],
    domain: str,
    service: str,
    source: str,
    data: dict[str, Any] | None = None,
    target_entity_id: str | None = None,
) -> CommandIntent | None:
    """Собрать команду обогревателю в его собственном домене.

    Обогреватель — это `switch.*` с таймером `number.*`, а не `climate.*`:
    команды для кондиционера и термостатов тут не годятся, Home Assistant их
    отвергнет, и отказ выглядел бы как «устройство не отвечает».

    Args:
        context: Контекст перехода с ``entity_id`` обогревателя.
        domain: Домен команды: ``number`` для таймера, ``switch`` для включения.
        service: Сервис Home Assistant.
        source: Источник для аудита и блокировок; по нему видно, каким путём
            пошла команда — через таймер или без него.
        data: Дополнительные поля команды.
        target_entity_id: Сущность, которой адресована команда. По умолчанию —
            сам обогреватель, но для ``number.set_value`` это должен быть таймер:
            Home Assistant не найдёт ``switch.*`` в домене ``number`` и откажет,
            а платформа сочтёт команду отправленной.

    Returns:
        Команда либо ``None``, если обогреватель не указан.
    """
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning(f"{source}: нет entity_id обогревателя в контексте")
        return None
    logger.info(
        f"Создаю команду {domain}.{service} для {target_entity_id or entity_id}, "
        f"данные: {data or {}}"
    )
    return CommandIntent(
        device_id=target_entity_id or entity_id,
        domain=domain,
        service=service,
        data=data or {},
        priority=context.get("priority", 50),
        source=source,
        # Признак обхода блокировки едет из события: движок ставит его для
        # событий из SAFETY_EVENTS (`engine.py:126-128`). Без этого суточное
        # событие не погасило бы обогреватель, включённый человеком, а
        # «ручное вмешательство переживает автоматику» держалось бы случайно.
        bypass_lockout=bool(context.get("bypass_lockout", False)),
    )


#: Сколько секунд в одной минуте. Таймер обогревателя измеряется в секундах, а
#: решения платформы принимаются в минутах, поэтому перевод стоит в одной точке.
SECONDS_PER_MINUTE = 60

#: Единицы измерения, которые таймер обогревателя может иметь. Значение
#: сравнивается приведённым к нижнему регистру и без пробелов: Home Assistant
#: пишет ``s``, ``sec``, ``min`` по-разному в зависимости от интеграции, и
#: несовпадение регистра не должно молча возвращаться к минутам.
_TIMER_UNIT_ALIASES: dict[str, str] = {
    "s": "s",
    "sec": "s",
    "secs": "s",
    "second": "s",
    "seconds": "s",
    "мин": "min",
    "min": "min",
    "mins": "min",
    "minute": "min",
    "minutes": "min",
}

#: Единица по умолчанию, когда устройство её не назвало. Минуты, а не секунды:
#: исторически платформа отправляла минуты, и если бы дефолт был другим, дома
#: с молчаливо неизвестной единицей получили бы час работы вместо получаса.
DEFAULT_TIMER_UNIT = "min"


def normalize_timer_unit(unit: Any) -> str | None:
    """Привести единицу измерения таймера к канону: ``s`` или ``min``.

    Args:
        unit: Единица как её назвало устройство, из манифеста или Home Assistant.

    Returns:
        ``"s"``, ``"min"`` либо ``None``, если единица не распознана.
    """
    if not isinstance(unit, str):
        return None
    return _TIMER_UNIT_ALIASES.get(unit.strip().lower())


def _timer_duration(context: dict[str, Any]) -> tuple[float, str]:
    """Перевести длительность работы в единицу измерения таймера.

    Боевой дефект 2026-10-11: платформа отправляла ``run_minutes`` (15) прямо в
    ``number.set_value``, а таймер обогревателя измеряется в секундах. Home
    Assistant принимала значение, обогреватель включался и гас через 15 секунд —
    а автомат честно отрабатывал свой таймер и выходил по ``timeout``. Итог:
    обогрев не работал сутки, и ни один признак это не показывал.

    Args:
        context: Контекст перехода с ``run_minutes`` и, возможно, ``timer_unit``.

    Returns:
        Пара ``(значение, единица)``. При нераспознанной единице возвращаются
        минуты и пометка ``assumed_unit`` в данных — угадывание обязано быть
        видимым, иначе тот же баг вернётся на другом устройстве.
    """
    minutes = context.get("run_minutes", DEFAULT_HEATER_RUN_MINUTES)
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes <= 0:
        minutes = DEFAULT_HEATER_RUN_MINUTES

    unit = normalize_timer_unit(context.get("timer_unit"))
    assumed = unit is None
    if unit is None:
        unit = DEFAULT_TIMER_UNIT

    value = float(minutes) * SECONDS_PER_MINUTE if unit == "s" else float(minutes)
    # Таймер целочисленный (step 1), а `number.set_value` на дробном значении
    # отвергается: значение округляется к тому, что устройство умеет.
    if float(value).is_integer():
        value = int(value)
    return value, unit if not assumed else DEFAULT_TIMER_UNIT


def timer_assumption_flag(unit: str, assumed: bool) -> str | None:
    """Пометка угаданной единицы для данных команды.

    Args:
        unit: Единица, по которой посчитано значение.
        assumed: Единица была угадана, а не прочитана.

    Returns:
        ``"min"``, если единица угадана, иначе ``None``.
    """
    return unit if assumed else None


def heater_timer_on(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Включить обогреватель на заданное время через его собственный таймер.

    Требование владельца (FR-004): обогреватель включается «на 15 минут», а не
    просто «включить». Пока идёт таймер обогревателя, платформа не обязана
    ничего решать; когда таймер истечёт, придёт новое показание датчика и
    решение будет принято заново. Так обогреватель не может остаться включённым
    навсегда, даже если датчик температуры перестанет отвечать.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``, ``heater_timer`` и ``run_minutes``.

    Returns:
        Шаги команды по порядку: прибор включается, затем таймер. Если таймер в
        манифесте не задан — единственный шаг включения; без обогревателя —
        пустой список.
    """
    del state
    timer = context.get("heater_timer")
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning("heater_timer_on: нет entity_id обогревателя в контексте")
        return []

    minutes = context.get("run_minutes", DEFAULT_HEATER_RUN_MINUTES)
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes <= 0:
        minutes = DEFAULT_HEATER_RUN_MINUTES

    if not timer:
        logger.warning(
            f"Обогреватель {entity_id} включается без таймера: таймер не задан в "
            "манифесте, выключит датчик. Если датчик откажет, обогреватель "
            "останется работать — это защита, которой у нас больше нет"
        )
        return _single_step(_heater_intent(context, "switch", "turn_on", "heater_on_no_timer"))

    value, unit = _timer_duration(context)
    # В данных команды — только `value`. Служебные поля (`timer_unit`,
    # `assumed_unit`) Home Assistant отвергает с 400 Bad Request: у сервиса
    # `number.set_value` нет таких параметров. Проверено в доме 2026-10-11 —
    # вместе с лишним ключом не применялся весь таймер, то есть обогрев
    # включался и гас без всякой защиты. Такая отметка нужна журналу, а не
    # устройству, поэтому она живёт в намерении и в предупреждении ниже.
    data: dict[str, Any] = {"value": value}
    assumed_unit = timer_assumption_flag(
        unit, normalize_timer_unit(context.get("timer_unit")) is None
    )
    if assumed_unit:
        logger.warning(
            f"{entity_id}: единица измерения таймера {context.get('timer_unit')!r} "
            f"не распознана, приняты {assumed_unit}. Если устройство измеряет "
            "таймер в секундах, обогреватель выключится через минуты вместо "
            "получаса — задайте timer_unit в манифесте"
        )

    # Порядок обязателен и выяснен в доме (2026-10-11): таймер принимается
    # только на уже включённом приборе. Таймер, записанный на выключенный
    # обогреватель, Home Assistant сохраняет без ошибки, а греть никто не
    # будет — отказ выглядит как успех, и обогрев молчит.
    on_step = _heater_intent(context, "switch", "turn_on", "heater_timer_on")
    timer_step = _heater_intent(
        context,
        "number",
        "set_value",
        "heater_timer_on",
        data=data,
        # Адресат — таймер, а не переключатель: `number.set_value` для
        # `switch.*` Home Assistant отвергает, и команда пропала бы молча.
        target_entity_id=timer,
    )
    # Единица измерения — сведения для разбора, а не параметр сервиса: в `data`
    # она даёт 400 Bad Request и вместе с собой уносит весь таймер.
    if timer_step is not None:
        timer_step.timer_unit = unit
    return _with_requirement([on_step, timer_step], timer_step, "on", state_entity=entity_id)


def _single_step(intent: CommandIntent | None) -> list[CommandIntent]:
    """Обернуть одно намерение в список шагов.

    Args:
        intent: Намерение либо ``None``.

    Returns:
        Список из одного намерения либо пустой список.
    """
    return [intent] if intent is not None else []


def _with_requirement(
    steps: list[CommandIntent | None],
    guarded: CommandIntent | None,
    required_state: str,
    state_entity: str | None = None,
) -> list[CommandIntent]:
    """Пометить шаг условием по состоянию прибора, выбросив пустые шаги.

    Args:
        steps: Шаги команды по порядку.
        guarded: Шаг, который отправляется только при нужном состоянии прибора.
        required_state: Ожидаемое состояние прибора (``on``/``off``).
        state_entity: Прибор, состояние которого проверяется. По умолчанию —
            адресат шага, но для таймера это должен быть сам обогреватель:
            состояние таймера — это «сколько секунд осталось», а не вкл/выкл.

    Returns:
        Готовые к отправке шаги.
    """
    result = [step for step in steps if step is not None]
    for step in result:
        if step is guarded:
            step.requires_state = required_state
            if state_entity:
                step.state_entity = state_entity
    return result


def heater_on(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить обогреватель напрямую, без его таймера.

    Отдельное действие нужно для домов, где таймера нет вовсе, и для ручной
    правки поведения; решение «через таймер или напрямую» принимает
    `heater_timer_on`, а этот путь оставлен явным.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` обогревателя.

    Returns:
        Команда включения либо ``None`` без обогревателя.
    """
    del state
    return _heater_intent(context, "switch", "turn_on", "heater_on")


def heater_off(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Выключить обогреватель: цель достигнута или время работы вышло.

    Порядок тот же, что и при включении, только наоборот: сначала таймер в ноль,
    затем выключение. Таймер, оставленный на выключенном приборе, включит его
    позже сам — обогреватель загорается через несколько минут после того, как
    платформа решила, что комната достаточно тёплая.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` обогревателя и, возможно, таймером.

    Returns:
        Шаги выключения по порядку.
    """
    del state
    return _heater_off_steps(context, "heater_off", emergency=False)


def heater_emergency_off(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Выключить обогреватель принудительно — минуя блокировку.

    Вызывается по истечении страховочного таймера: автомат отработал положенное
    время, а нового решения не принял никто, потому что датчик молчит или отказал.

    Блокировка обходится намеренно. Блокировка отвечает на вопрос «не мешай ли
    человеку», и человек, включивший обогреватель руками, вправе получить его
    выключенным по таймеру автоматики. Обратное неверно: в бою 2026-10-11
    блокировка оставила масляный радиатор включённым на пять часов после
    истечения таймера, потому что датчик комнаты перестал присылать показания.
    Защита от неудобства не должна превращаться в открытый обогрев.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` обогревателя и, возможно, таймером.

    Returns:
        Шаги выключения по порядку.
    """
    del state
    return _heater_off_steps(context, "heater_emergency_off", emergency=True)


def _heater_off_steps(
    context: dict[str, Any],
    source: str,
    emergency: bool,
) -> list[CommandIntent]:
    """Шаги выключения обогревателя: таймер в ноль, затем прибор.

    Требования состояния здесь намеренно нет. Чтобы выключить прибор, он должен
    быть **включён**, а требование ``off`` делало бы команду неотправляемой
    никогда: прибор, который и так выключен, прошёл бы проверку, а включённый
    остался бы греться.

    Args:
        context: Контекст с ``entity_id`` обогревателя и, возможно, таймером.
        source: Источник для аудита и блокировок.
        emergency: Обойти ли блокировку ручного вмешательства.

    Returns:
        Шаги выключения по порядку.
    """
    timer = context.get("heater_timer")
    emergency_ctx = {**context, "bypass_lockout": True} if emergency else context
    off_step = _heater_intent(emergency_ctx, "switch", "turn_off", source)
    if not timer or off_step is None:
        return _single_step(off_step)

    zero_step = _heater_intent(
        emergency_ctx,
        "number",
        "set_value",
        source,
        # Только `value`: `timer_unit` — сведения для журнала, а не параметр
        # сервиса. В `data` он даёт `extra keys not allowed`, Home Assistant
        # отвергает весь вызов, и обнуление таймера не происходит (живая
        # находка 01.11 — вместе с ним пропадало и выключение прибора).
        data={"value": 0},
        target_entity_id=timer,
    )
    if zero_step is not None:
        # Обнуление — подготовка, а не цель: если оно не удалось, прибор всё
        # равно нужно выключить. Оставить обогреватель включённым хуже, чем
        # оставить таймер, который потом попробует включить его снова.
        zero_step.best_effort = True
    return [step for step in (zero_step, off_step) if step is not None]


def ac_cool_on(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить охлаждение кондиционером на потолок комфорта.

    Охлаждать платформа умеет только до той температуры, которую владелец назвал
    комфортной (`comfort_max`). Охлаждать «прохладнее» без его решения — значит
    перестудить дом и получить ту же жалобу, с которой начиналось: слишком жарко
    или слишком холодно, но не по вашему слову.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` кондиционера и ``comfort_max``.

    Returns:
        Команда ``climate.set_temperature`` либо ``None``, если нет кондиционера
        или потолка комфорта.
    """
    del state
    comfort_max = context.get("comfort_max")
    if comfort_max is None or isinstance(comfort_max, bool):
        logger.warning("ac_cool_on: нет потолка комфорта — охлаждать не к чему")
        return None
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning("ac_cool_on: нет entity_id кондиционера в контексте")
        return None
    # Потолок комфорта едет в команду именно как температура: `_climate_intent`
    # читает `target_temp`, и без подстановки `climate.set_temperature` ушёл бы
    # без неё — как в дефекте #71, только наоборот (там терялось заданное, здесь
    # не подставлялось рассчитанное).
    return _climate_intent(
        {**context, "target_temp": comfort_max},
        "set_temperature",
        "ac_cool_on",
    )


def ac_forced_off(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Немедленно выключить кондиционер — защита зимой.

    Кондиционер, работающий на охлаждение при отрицательной температуре, повреждает
    компрессор (FR-011). Поэтому зимой любая команда его включения гасится сразу,
    а владелец получает уведомление: молча выключенный кондиционер выглядит как
    «платформа решила не охлаждать», и поломку техники никто не заметит.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` кондиционера.

    Returns:
        Команда ``climate.turn_off`` либо ``None`` без кондиционера.
    """
    del state
    return _climate_intent(context, "turn_off", "ac_forced_off")


def climate_heat(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить отопление на заданную температуру.

    Args:
        state: Текущее состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``target_temperature``.

    Returns:
        Команда установки температуры либо ``None`` без устройства.
    """
    return _climate_intent(context, "set_temperature", "climate_heat")


def climate_cool(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить охлаждение на заданную температуру.

    Args:
        state: Текущее состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``target_temperature``.

    Returns:
        Команда установки температуры либо ``None`` без устройства.
    """
    return _climate_intent(context, "set_temperature", "climate_cool")


def climate_off(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Выключить климатическое устройство.

    Args:
        state: Текущее состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда выключения либо ``None`` без устройства.
    """
    return _climate_intent(context, "turn_off", "climate_off")
