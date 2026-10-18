"""Зеркало состояний автоматов в помощники Home Assistant (B79).

Состояние автомата должно жить в доме: владелец смотрит дом из Home Assistant, и
там у него появляется нативная история. Проверки держат то, на чём легко
ошибиться:

* помощники создаются **один раз** — повторный старт находит существующих по
  имени, иначе каждый перезапуск плодил бы дубликаты;
* если дом не отдал список, создавать нельзя — иначе дубликаты появятся при
  любом сбое связи;
* запись идёт в **того** помощника, которого назвал дом (идентификатор сущности
  мог быть выдан иначе), а не в выдуманный;
* отказ дома не ломает переходы (FR-009, R-06).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

import pytest

from core.services.fsm_helper_mirror import FsmHelperMirror


FSM = "light.svet_nad_stolom_lighting_10"
FSM_NAME = "fsm light.svet_nad_stolom_lighting_10"


class FakeHome:
    """Дом-двойник: помнит помощников и записанные значения."""

    def __init__(self, helpers: dict[str, str] | None = None, *, list_fails: bool = False) -> None:
        self.helpers = dict(helpers or {})  # имя → id
        self.list_fails = list_fails
        self.created: list[str] = []
        self.written: list[tuple[str, str]] = []

    async def send(self, command_type: str, **payload: Any) -> dict[str, Any]:
        """Ответить на команду API помощников.

        Args:
            command_type: Тип команды.
            **payload: Поля команды.

        Returns:
            Ответ дома.
        """
        if command_type == "input_text/list":
            if self.list_fails:
                return {"success": False, "error": {"code": "not_connected"}}
            return {
                "success": True,
                "result": [{"id": helper, "name": name} for name, helper in self.helpers.items()],
            }
        if command_type == "input_text/create":
            name = str(payload.get("name"))
            helper = name.replace(" ", "_").replace(".", "_").lower()
            self.helpers[name] = helper
            self.created.append(helper)
            return {"success": True, "result": {"id": helper}}
        return {"success": False, "error": {"code": "unknown_command"}}

    async def write(self, entity_id: str, value: str) -> bool:
        """Запомнить запись значения.

        Args:
            entity_id: Сущность помощника.
            value: Значение.

        Returns:
            True.
        """
        self.written.append((entity_id, value))
        return True


class TestEnsureCreatesOnce:
    """Помощники создаются ровно один раз."""

    @pytest.mark.asyncio
    async def test_missing_helper_is_created(self) -> None:
        """Нет помощника — платформа создаёт его сама."""
        home = FakeHome()
        mirror = FsmHelperMirror(send_command=home.send, publish_state=home.write)

        mapping = await mirror.ensure([FSM])

        assert mapping[FSM] == "input_text.fsm_light_svet_nad_stolom_lighting_10"
        assert home.created == ["fsm_light_svet_nad_stolom_lighting_10"]
        assert mirror.describe()["created"] == 1

    @pytest.mark.asyncio
    async def test_existing_helper_is_found_by_name(self) -> None:
        """Помощник прошлого запуска находится по имени, а не создаётся заново."""
        home = FakeHome({FSM_NAME: "fsm_light_svet_nad_stolom_lighting_10"})
        mirror = FsmHelperMirror(send_command=home.send, publish_state=home.write)

        mapping = await mirror.ensure([FSM])

        assert mapping[FSM] == "input_text.fsm_light_svet_nad_stolom_lighting_10"
        assert home.created == [], "существующий помощник пересоздан"

    @pytest.mark.asyncio
    async def test_repeat_ensure_does_not_create_again(self) -> None:
        """Повторный вызов не плодит дубликаты."""
        home = FakeHome()
        mirror = FsmHelperMirror(send_command=home.send, publish_state=home.write)

        await mirror.ensure([FSM])
        await mirror.ensure([FSM])

        assert home.created == ["fsm_light_svet_nad_stolom_lighting_10"]

    @pytest.mark.asyncio
    async def test_helper_id_from_home_wins(self) -> None:
        """Если дом выдал другой идентификатор, пишем в него, а не в выдуманный."""
        home = FakeHome({FSM_NAME: "custom_helper_id"})
        mirror = FsmHelperMirror(send_command=home.send, publish_state=home.write)

        mapping = await mirror.ensure([FSM])
        await mirror.write(FSM, "ON_MOTION")

        assert mapping[FSM] == "input_text.custom_helper_id"
        assert home.written == [("input_text.custom_helper_id", "ON_MOTION")]

    @pytest.mark.asyncio
    async def test_unreachable_home_creates_nothing(self) -> None:
        """Нет списка — нет создания: иначе при сбое связи появятся дубликаты."""
        home = FakeHome(list_fails=True)
        mirror = FsmHelperMirror(send_command=home.send, publish_state=home.write)

        mapping = await mirror.ensure([FSM])

        assert mapping == {}
        assert home.created == []
        assert mirror.describe()["failed"] > 0


class TestWrite:
    """Запись состояния не зависит от создания."""

    @pytest.mark.asyncio
    async def test_write_without_ensure_uses_computed_id(self) -> None:
        """Переход может прийти раньше создания — адрес считается по правилу."""
        home = FakeHome()
        mirror = FsmHelperMirror(send_command=home.send, publish_state=home.write)

        ok = await mirror.write(FSM, "ON_HOLD")

        assert ok is True
        assert home.written == [("input_text.fsm_light_svet_nad_stolom_lighting_10", "ON_HOLD")]

    @pytest.mark.asyncio
    async def test_empty_state_is_not_written(self) -> None:
        """Пустое состояние не пишется: помощник не должен обнуляться зря."""
        home = FakeHome()
        mirror = FsmHelperMirror(send_command=home.send, publish_state=home.write)

        assert await mirror.write(FSM, "") is False
        assert home.written == []

    @pytest.mark.asyncio
    async def test_disabled_mirror_does_nothing(self) -> None:
        """Без зависимостей зеркало молчит."""
        mirror = FsmHelperMirror()

        assert await mirror.ensure([FSM]) == {}
        assert await mirror.write(FSM, "OFF") is False
