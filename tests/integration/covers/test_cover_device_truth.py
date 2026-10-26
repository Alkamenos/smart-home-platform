"""Штора, закрытая вне платформы: модель уступает прибору (B89).

Та же находка, что у света: штору мог закрыть кто-то вне платформы — человек
выключателем или автоматизация Home Assistant. Ручное действие платформа опознаёт
по `user_id`, поэтому такое изменение не замечает и продолжает считать штору
открытой (боевой разбор 2026-10-17: штора спальни стояла в расхождении
«автомат `OPEN`, прибор `closed`»).

Шаблон `cover_modes` получил переход «прибор не работает → `CLOSED`» по
одноразовому признаку `_device_is_off`, и стоит он **до** повтора решения: у одной
пары (состояние, событие) побеждает первое условие, которое прошло. Дальше решение
принимается обычным путём — на смену флагов дома (`settings_changed`) автомат
откроет штору снова, если так велят правила.

Поведение самого механизма проверено на свете
(`tests/integration/lighting/test_light_device_truth.py`): движок тот же, и путь
перехода одинаков. Здесь проверяется порядок объявления — без него признак
никогда не сработает, а поломка эта тихая: тесты продолжат проходить.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

import yaml


#: Событие сторожа о расхождении прибора и решения.
DIVERGED = "device_state_diverged"


def test_cover_opened_by_hand_is_adopted() -> None:
    """Обратная правда: открытую вручную штору модель принимает как OPEN.

    Сторож шлёт `_device_is_on`, и переход `CLOSED -> OPEN` обязан стоять до
    повтора «закрыть», иначе повтор выиграет и платформа снова закроет штору
    за человеком (B104).
    """
    template = yaml.safe_load(Path("src/features/cover_modes.yaml").read_text(encoding="utf-8"))
    transitions = template["transitions"]

    adoption = [
        index
        for index, transition in enumerate(transitions)
        if transition.get("trigger") == DIVERGED and transition.get("guard") == "device_is_on"
    ]
    assert adoption, "cover_modes: перехода «модель принимает OPEN» нет"
    assert all(transitions[index].get("to_state") == "OPEN" for index in adoption), (
        "открытая штора должна приводить модель в OPEN"
    )
    assert all(transitions[index].get("action") is None for index in adoption), (
        "принятие факта не должно командовать прибором"
    )

    repeat = [
        index
        for index, transition in enumerate(transitions)
        if transition.get("trigger") == DIVERGED
        and transition.get("from_state") == "CLOSED"
        and transition.get("guard") != "device_is_on"
    ]
    assert repeat, "cover_modes: у CLOSED нет повтора решения"
    assert min(adoption) < min(repeat), (
        "повтор «закрыть» стоит раньше принятия OPEN — штора снова закроется"
    )


def test_cover_adoption_precedes_the_repeat() -> None:
    """Признание правды объявлено и стоит до повтора решения.

    Иначе повтор («штору открыть») выигрывал бы у признания правды, и расхождение
    оставалось бы навсегда: ровно боевой случай 2026-10-17.
    """
    template = yaml.safe_load(Path("src/features/cover_modes.yaml").read_text(encoding="utf-8"))
    transitions = template["transitions"]

    adoption = [
        index
        for index, transition in enumerate(transitions)
        if transition.get("trigger") == DIVERGED and transition.get("guard") == "device_is_off"
    ]
    assert adoption, "cover_modes: перехода «модель уступает прибору» нет"
    assert all(transitions[index].get("action") is None for index in adoption), (
        "приведение модели в соответствие не должно командовать прибором"
    )

    for index in adoption:
        adopted = transitions[index]
        assert adopted.get("to_state") == "CLOSED", (
            "штора стоит закрытой — приводить модель к прибору значит признать CLOSED"
        )
        repeat = [
            other
            for other in range(len(transitions))
            if other != index
            and transitions[other].get("trigger") == DIVERGED
            and transitions[other].get("from_state") == adopted.get("from_state")
            and transitions[other].get("guard") != "device_is_off"
        ]
        assert repeat, f"cover_modes: у {adopted.get('from_state')!r} нет повтора решения"
        assert index < min(repeat), (
            f"cover_modes: повтор решения для {adopted.get('from_state')!r} стоит "
            f"раньше ({min(repeat)}) признания правды ({index}) — признак никогда "
            "не сработает"
        )
