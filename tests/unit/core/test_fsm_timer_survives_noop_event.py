"""Событие без перехода не должно отменять отложенный переход.

Найдено на живом стенде 2026-10-07, при проверке починки #78 в бою.

Симптом
-------

Восстановленный таймер был взведён на 30 с (`state held for 0.0s, timer armed for
30.0s`), и через минуту сторож честно сообщил `stuck: true` — то есть состояние
`ON_MOTION` не ушло по таймауту. По коду починки причин быть не могло: таймер
взведён, остаток верный.

Причина в другом месте. `FSMEngine.trigger()` отменяет таймеры **первым
действием**, до того как разберётся, состояние вообще меняется:

```python
# Cancel any existing timers before processing new trigger
await self._cancel_timers(entity_id, log)
```

А дальше событие может не дать перехода вовсе: в `lighting.yaml` нет перехода по
триггеру `motion_cleared`, и в журнале боевой базы это видно прямо — из
`ON_MOTION` приходят `motion_detected` и `motion_cleared`, и все они заканчиваются
`no_transition`:

```
19:42:27  ON_MOTION  motion_detected  no_transition
19:42:42  ON_MOTION  motion_cleared   no_transition
19:43:37  ON_MOTION  motion_detected  no_transition
```

Датчик движения в жилой комнате шлёт события каждые 15–60 с. Каждое из них
съедало таймер и **не взводило новый**, потому что новый взводится только в пути
выполненного перехода. То есть отложенный переход отменялся приходящими событиями
и никогда не наступал — свет не гас никогда.

Это ровно наблюдавшийся в доме дефект, и он не был связан с перезапуском:
таймаутные переходы не срабатывали и в живом процессе.

Почему это не поймали прежние проверки
-------------------------------------

Прежние проверки ждали тишины: пока событий нет, таймер живёт и срабатывает.
Проверка на тишину доказывает, что таймер работает в покое — и ничего не говорит
о том, что происходит, когда события идут. В доме события идут всегда.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio

import pytest

from core.fsm.engine import FSMDefinition, FSMEngine, Transition


ENTITY_ID = "light.kitchen_lighting_10"

#: Ожидание и интервал взяты пропорционально боевым (30 с и 15–60 с), а не
#: буквально: проверка живёт столько же, сколько ждёт, и превышение лимита
#: теста (30 с) дало бы падение по таймауту вместо падения по смыслу. Соотношение
#: «ожидание вдвое больше интервала событий» — то, что делало дефект видимым.
MOTION_TIMEOUT_SEC = 6.0

#: Интервал между событиями датчика: втрое чаще, чем таймаут, — как в доме, где
#: датчик шлёт события каждые 15–60 с при ожидании 30 с.
SENSOR_INTERVAL_SEC = 2.0


def _lighting_definition() -> FSMDefinition:
    """Собрать определение автомата освещения из шаблона.

    Returns:
        Определение с тем же набором переходов, что и в `lighting.yaml`.
    """
    return FSMDefinition(
        entity_id=ENTITY_ID,
        initial_state="OFF",
        states=["OFF", "ON_MOTION", "ON_MANUAL"],
        transitions=[
            Transition(
                from_state="OFF",
                to_state="ON_MOTION",
                trigger="motion_detected",
                action=lambda *a, **k: None,
            ),
            # `motion_cleared` в шаблоне нет — это факт, а не допущение: без него
            # отклонения `no_transition` в боевом журнале не объяснить.
            Transition(
                from_state="ON_MOTION",
                to_state="OFF",
                trigger="timeout",
                action=lambda *a, **k: None,
                timeout_sec=MOTION_TIMEOUT_SEC,
            ),
        ],
    )


@pytest.mark.asyncio
class TestNoopEventKeepsTimer:
    """Событие без перехода не отменяет отложенный переход."""

    async def test_repeated_noop_events_do_not_starve_timer(self) -> None:
        """Пока идут события без перехода, отложенный переход наступает.

        Returns:
            Ничего.
        """
        engine = FSMEngine()
        engine.register_definition(_lighting_definition())
        await engine.trigger(ENTITY_ID, "motion_detected")

        state = engine.get_state(ENTITY_ID)
        assert state is not None
        assert state.current_state == "ON_MOTION"
        assert engine._timers.get(ENTITY_ID) is not None, (  # noqa: SLF001
            "переход по движению обязан взвести таймер"
        )

        # Ждём дольше объявленного ожидания, всё это время подбрасывая события
        # датчика — как в доме.
        deadline = MOTION_TIMEOUT_SEC + 1
        elapsed = 0.0
        while elapsed < deadline:
            await asyncio.sleep(SENSOR_INTERVAL_SEC)
            elapsed += SENSOR_INTERVAL_SEC
            # Событие, для которого в шаблоне нет перехода: состояние не должно
            # меняться, и таймер не должен исчезать.
            await engine.trigger(ENTITY_ID, "motion_cleared")

        state = engine.get_state(ENTITY_ID)
        assert state is not None
        assert state.current_state == "OFF", (
            f"автомат всё ещё в `{state.current_state}`, хотя с момента входа "
            f"прошло {deadline:.1f} с при ожидании {MOTION_TIMEOUT_SEC:.1f} с. "
            f"Приходящие события датчика съедали таймер: он отменялся в начале "
            f"`trigger()` до разбора перехода, а новый не взводился, потому что "
            f"перехода не было. Именно поэтому свет не гас в доме — и это не "
            f"было связано с перезапуском"
        )

    async def test_noop_event_keeps_timer_alive(self) -> None:
        """После события без перехода таймер остаётся взведённым.

        Returns:
            Ничего.
        """
        engine = FSMEngine()
        engine.register_definition(_lighting_definition())
        await engine.trigger(ENTITY_ID, "motion_detected")

        assert engine._timers.get(ENTITY_ID) is not None  # noqa: SLF001

        transitioned = await engine.trigger(ENTITY_ID, "motion_cleared")

        assert transitioned is False, "перехода по motion_cleared в шаблоне нет"
        assert engine._timers.get(ENTITY_ID) is not None, (  # noqa: SLF001
            "событие без перехода отменило таймер. Отмена здесь означает "
            "«состояние изменилось, прежнее ожидание больше не действует» — "
            "но состояние не изменилось, и отменять было нечего"
        )

    async def test_real_transition_still_cancels_old_timer(self) -> None:
        """Настоящий переход отменяет прежний таймер — иначе сработает не тот.

        Returns:
            Ничего.
        """
        engine = FSMEngine()
        engine.register_definition(_lighting_definition())
        await engine.trigger(ENTITY_ID, "motion_detected")
        first_timer = engine._timers.get(ENTITY_ID)  # noqa: SLF001
        assert first_timer is not None

        # Ручное выключение — настоящий переход из ON_MOTION.
        await engine.trigger(ENTITY_ID, "manual_switch_off", external_ctx={"new_state": "on"})

        state = engine.get_state(ENTITY_ID)
        assert state is not None
        assert first_timer.cancelled or first_timer.done, (
            "таймер прежнего состояния не отменён: он сработал бы позже и "
            "увёл бы автомат не туда. Отмена обязана быть на настоящем переходе — "
            "проверка выше требует не отменять её на событии без перехода, "
            "здесь — отменять"
        )
