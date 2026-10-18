"""Команда не уходит, если прибор уже в этом состоянии (B95).

Замечание владельца 2026-10-19: у боевого рекуператора от каждой команды
вспыхивает дисплей, а команды уходили и когда режим не менялся — на каждом
`settings_changed` автомат заново ставил тот же режим и ту же скорость (26 команд
за полчаса).

Правило: намерение несёт `skip_if` (состояние и атрибуты прибора), диспетчер
читает снимок прибора и не отправляет команду, если всё совпало. Границы важны
не меньше самого правила:

* расхождение — команду отправляем (человек переключил, прибор откатился);
* прочитать не удалось — отправляем: неизвестность не подтверждение;
* адаптер не умеет читать снимок — отправляем.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

from core import CommandDispatcher, CommandIntent
from core.commands.dispatcher import _values_match


DEVICE = "fan.base_smart_2"


class _Adapter:
    """Адаптер-двойник: помнит вызовы и отдаёт заданный снимок прибора."""

    def __init__(self, snapshot: dict[str, Any] | None = None) -> None:
        self.snapshot = snapshot
        self.calls: list[dict[str, Any]] = []

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Запомнить вызов сервиса.

        Args:
            domain: Домен сервиса.
            service: Имя сервиса.
            entity_id: Сущность.
            data: Данные вызова.
            trace_id: Трасса.

        Returns:
            True.
        """
        self.calls.append({"service": service, "entity_id": entity_id, "data": data or {}})
        return True

    async def get_entity_snapshot(self, entity_id: str) -> dict[str, Any] | None:
        """Отдать снимок прибора.

        Args:
            entity_id: Сущность.

        Returns:
            Снимок либо None.
        """
        del entity_id
        return self.snapshot


class _AdapterWithoutSnapshot:
    """Адаптер без чтения снимка: проверка должна отправить команду."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Запомнить вызов.

        Args:
            domain: Домен сервиса.
            service: Имя сервиса.
            entity_id: Сущность.
            data: Данные вызова.
            trace_id: Трасса.

        Returns:
            True.
        """
        del domain, data, trace_id
        self.calls.append(f"{service}:{entity_id}")
        return True


def _intent(**skip_if: Any) -> CommandIntent:
    """Намерение задать режим рекуператора.

    Args:
        **skip_if: Состояние и атрибуты, при которых команда не нужна.

    Returns:
        Намерение.
    """
    return CommandIntent(
        device_id=DEVICE,
        domain="fan",
        service="set_preset_mode",
        data={"preset_mode": "Приток"},
        priority=50,
        source="fan_set_preset",
        skip_if=skip_if or None,
    )


class TestSkipWhenAlreadyThere:
    """Команда не уходит, когда прибор уже в нужном состоянии."""

    @pytest.mark.asyncio
    async def test_matching_state_and_preset_is_skipped(self) -> None:
        """Режим и включённость совпали — команды нет, но это не отказ."""
        adapter = _Adapter({"state": "on", "preset_mode": "Приток"})
        dispatcher = CommandDispatcher(ha_adapter=adapter)

        sent = await dispatcher.submit(_intent(state="on", preset_mode="Приток"))

        assert sent is True, "пропуск команды — не отказ, автомат должен идти дальше"
        assert adapter.calls == []

    @pytest.mark.asyncio
    async def test_preset_case_and_spaces_do_not_matter(self) -> None:
        """«Приток » и «приток» — тот же режим."""
        adapter = _Adapter({"state": "on", "preset_mode": " приток "})
        dispatcher = CommandDispatcher(ha_adapter=adapter)

        await dispatcher.submit(_intent(state="on", preset_mode="Приток"))

        assert adapter.calls == []

    @pytest.mark.asyncio
    async def test_percentage_compared_as_number(self) -> None:
        """14 и 14.0 — одна и та же скорость."""
        adapter = _Adapter({"state": "on", "percentage": 14.0})
        dispatcher = CommandDispatcher(ha_adapter=adapter)
        intent = CommandIntent(
            device_id=DEVICE,
            domain="fan",
            service="turn_on",
            data={"percentage": 14},
            priority=50,
            source="fan_set_percentage",
            skip_if={"state": "on", "percentage": 14},
        )

        await dispatcher.submit(intent)

        assert adapter.calls == []


class TestSendWhenItMatters:
    """Команда уходит, когда состояние не совпало или неизвестно."""

    @pytest.mark.asyncio
    async def test_other_preset_is_sent(self) -> None:
        """Прибор в другом режиме — команда нужна."""
        adapter = _Adapter({"state": "on", "preset_mode": "Рекуперация (зима)"})
        dispatcher = CommandDispatcher(ha_adapter=adapter)

        await dispatcher.submit(_intent(state="on", preset_mode="Приток"))

        assert [call["service"] for call in adapter.calls] == ["set_preset_mode"]

    @pytest.mark.asyncio
    async def test_off_device_is_sent(self) -> None:
        """Прибор выключен — включаем и ставим режим."""
        adapter = _Adapter({"state": "off", "preset_mode": "Приток"})
        dispatcher = CommandDispatcher(ha_adapter=adapter)

        await dispatcher.submit(_intent(state="on", preset_mode="Приток"))

        assert len(adapter.calls) == 1

    @pytest.mark.asyncio
    async def test_unreadable_snapshot_is_sent(self) -> None:
        """Прочитать не удалось — неизвестность не подтверждение."""
        adapter = _Adapter(None)
        dispatcher = CommandDispatcher(ha_adapter=adapter)

        await dispatcher.submit(_intent(state="on", preset_mode="Приток"))

        assert len(adapter.calls) == 1

    @pytest.mark.asyncio
    async def test_missing_attribute_is_sent(self) -> None:
        """Прибор не сообщил режим — отправляем, а не молчим."""
        adapter = _Adapter({"state": "on"})
        dispatcher = CommandDispatcher(ha_adapter=adapter)

        await dispatcher.submit(_intent(state="on", preset_mode="Приток"))

        assert len(adapter.calls) == 1

    @pytest.mark.asyncio
    async def test_adapter_without_snapshot_still_sends(self) -> None:
        """Адаптер не умеет читать снимок — команда уходит."""
        adapter = _AdapterWithoutSnapshot()
        dispatcher = CommandDispatcher(ha_adapter=adapter)

        await dispatcher.submit(_intent(state="on", preset_mode="Приток"))

        assert adapter.calls == [f"set_preset_mode:{DEVICE}"]

    @pytest.mark.asyncio
    async def test_intent_without_skip_if_is_sent(self) -> None:
        """Намерение без `skip_if` ведёт себя как прежде."""
        adapter = _Adapter({"state": "on", "preset_mode": "Приток"})
        dispatcher = CommandDispatcher(ha_adapter=adapter)

        await dispatcher.submit(_intent())

        assert len(adapter.calls) == 1


class TestValuesMatch:
    """Сравнение значений не выдумывает различий и не считает молчание согласием."""

    def test_none_is_not_a_match(self) -> None:
        """Молчание прибора — не подтверждение."""
        assert _values_match(None, "on") is False
        assert _values_match("on", None) is False

    def test_numbers_and_strings(self) -> None:
        """14 и «14.0» — одно значение, bool не путается с числом."""
        assert _values_match(14.0, 14) is True
        assert _values_match("14", 14) is True
        assert _values_match(True, 1) is False

    def test_text_is_normalised(self) -> None:
        """Регистр и пробелы в названии режима не различие."""
        assert _values_match(" Приток ", "приток") is True
        assert _values_match("Приток", "Рекуперация") is False
