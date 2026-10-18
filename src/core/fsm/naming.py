"""Имена автоматов и их зеркал в Home Assistant (B79).

Идентификатор экземпляра автомата собирается фабрикой из трёх частей:

    ``{id прибора}_{шаблон поведения}_{приоритет}``

Например, ``light.svet_nad_stolom_lighting_10``. Это имя знают все: движок,
журнал переходов, веб-интерфейс — и теперь дашборд Home Assistant, который
показывает состояние автомата. Поэтому правило живёт в одном месте, а не
повторяется строкой в фабрике, генераторе дашборда и зеркале.

Зеркало состояния — **вспомогательный элемент** Home Assistant (`input_text`):
он получает нативную историю в доме и не требует, чтобы владелец заводил
тридцать помощников руками (их создаёт платформа через API помощников).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import re


#: Домен вспомогательного элемента, в котором живёт состояние автомата.
HELPER_DOMAIN = "input_text"

#: Префикс идентификаторов помощников: отличает наши элементы от хозяйских.
HELPER_PREFIX = "fsm"

#: Запас длины значения: состояния автоматов короткие, но предел не должен
#: обрезать будущие имена («MISMATCH_DEVICE_OFF_DECISION_ON» — 30 символов).
HELPER_MAX_LENGTH = 255


def fsm_entity_id(device_id: str, template: str, priority: int) -> str:
    """Собрать идентификатор экземпляра автомата.

    Args:
        device_id: Идентификатор прибора в Home Assistant.
        template: Имя шаблона поведения (``lighting``, ``climate_control``).
        priority: Приоритет поведения из манифеста.

    Returns:
        Идентификатор автомата.
    """
    return f"{device_id}_{template or 'fsm'}_{priority}"


def helper_id(fsm_id: str) -> str:
    """Идентификатор помощника по имени автомата.

    Home Assistant собирает идентификатор сущности из имени так же: приводит к
    нижнему регистру и заменяет всё, кроме латиницы и цифр, на подчёркивание
    (проверено живьём 18.10: ``fsm light.svet_nad_stolom_lighting_10`` →
    ``fsm_light_svet_nad_stolom_lighting_10``).

    Args:
        fsm_id: Идентификатор автомата.

    Returns:
        Идентификатор помощника без домена.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", fsm_id.lower()).strip("_")
    return f"{HELPER_PREFIX}_{slug}" if slug else HELPER_PREFIX


def helper_entity_id(fsm_id: str) -> str:
    """Полный идентификатор сущности помощника.

    Args:
        fsm_id: Идентификатор автомата.

    Returns:
        Идентификатор вида ``input_text.fsm_…``.
    """
    return f"{HELPER_DOMAIN}.{helper_id(fsm_id)}"


def helper_name(fsm_id: str) -> str:
    """Имя помощника в Home Assistant — по нему зеркало находит его после старта.

    Имя намеренно техническое и латиницей: из него Home Assistant собирает
    идентификатор, и кириллица сделала бы его непредсказуемым (урок B79).

    Args:
        fsm_id: Идентификатор автомата.

    Returns:
        Имя помощника.
    """
    return f"{HELPER_PREFIX} {fsm_id}"
