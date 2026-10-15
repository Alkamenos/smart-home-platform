"""События солнца и модификатора «мы спим» в их настоящей форме.

Два сбоя, найденные разбором живого потока Home Assistant 2026-10-09:

1. **Событие солнца не выставляло светлоту.** В конверте ``event.data``
   поле ``new_state`` — словарь ``{"entity_id": ..., "state": ...}``, а условие
   сравнивало его со строкой ``"below_horizon"``. Сравнение словаря со строкой
   всегда даёт True: после любого события солнца платформа считала, что светло,
   и **вечером движение не включало свет** — самое время его включения. При
   перезапуске ночью состояние читалось по REST верно, и дефект проявлялся
   только после заката: вечер выглядел так, будто датчиков движения нет.

2. **Переключение «мы спим» в Home Assistant было невидимо платформе.**
   Сущность модификатора отфильтровывается как не-устройство, и включение
   «спим» никто не заметил: свет над столом продолжал гореть, а ночник не
   знал, что пора. Теперь переключение ``off -> on`` доносит событие
   ``sleep_started`` до платформы.

Форма конверта взята из ``tests/helpers/ha_stub.state_changed_event`` — той же,
что шлёт настоящий Home Assistant.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

import pytest

from adapters.ha_adapter import SimpleHAWebSocketClient
from tests.helpers.ha_stub import state_changed_event


#: Сущность-модификатор «мы спим» в Home Assistant.
MODIFIER = "input_boolean.sleep_mode"

#: Солнце.
SUN = "sun.sun"


def _client() -> SimpleHAWebSocketClient:
    """Клиент с фильтром, пропускающим только устройства.

    Returns:
        Клиент, готовый к доставке событий.
    """
    client = SimpleHAWebSocketClient(url="ws://localhost:8123", token="t")
    client.entity_filter_provider = lambda: ["light.svet_nad_stolom"]
    client.sleep_modifier_entity = MODIFIER
    client.filtered_entity_ids = ("light.svet_nad_stolom",)
    return client


def _payload(envelope: dict[str, Any]) -> dict[str, Any]:
    """Вынуть из конверта то, что уходит в ``_deliver``: ``event.data`` плюс контекст.

    Форма повторяет цикл чтения сокета: ``payload = event.data``, контекст
    подмешивается рядом — так Home Assistant и шлёт событие.

    Args:
        envelope: Конверт сообщения ``{"type": "event", "event": {...}}``.

    Returns:
        Событие для доставки.
    """
    event_data = envelope["event"]
    return {**event_data["data"], "context": event_data["context"]}


class TestSunEventCarriesRealStateShape:
    """Событие солнца в форме Home Assistant выставляет светлоту."""

    @pytest.mark.asyncio
    async def test_below_horizon_makes_evening_dark(self) -> None:
        """Закат значит «темно»: вечернее движение должно включать свет.

        Returns:
            Ничего.
        """
        client = _client()
        client.daylight = True  # платформа видела день

        payload = _payload(
            state_changed_event(SUN, new_state="below_horizon", old_state="above_horizon")
        )
        await client._deliver(payload)  # noqa: SLF001

        assert client.daylight is False, (
            "закат не погас светлоту: новый_state в событии — словарь, а условие "
            "ждало строку, и вечер движение не включало свет"
        )

    @pytest.mark.asyncio
    async def test_above_horizon_keeps_day(self) -> None:
        """Рассвет значит «светло».

        Returns:
            Ничего.
        """
        client = _client()
        client.daylight = False

        payload = _payload(
            state_changed_event(SUN, new_state="above_horizon", old_state="below_horizon")
        )
        await client._deliver(payload)  # noqa: SLF001

        assert client.daylight is True

    @pytest.mark.asyncio
    async def test_unknown_sun_state_keeps_previous(self) -> None:
        """Нераспознанное состояние солнца ничего не портит.

        Returns:
            Ничего.
        """
        client = _client()
        client.daylight = False

        payload = _payload(
            state_changed_event(SUN, new_state="unavailable", old_state="above_horizon")
        )
        await client._deliver(payload)  # noqa: SLF001

        assert client.daylight is False, "нераспознанное состояние изменило светлоту"


class TestModifierFlipNotifiesPlatform:
    """Переключение «мы спим» доносит событие до платформы."""

    @pytest.mark.asyncio
    async def test_turning_on_requests_sleep_started(self) -> None:
        """Включение модификатора вызывает уведомление платформы.

        Returns:
            Ничего.
        """
        client = _client()
        client.asleep = False
        seen: list[str] = []

        async def on_sleep_started() -> None:
            seen.append("sleep_started")

        client.on_sleep_started = on_sleep_started
        payload = _payload(state_changed_event(MODIFIER, new_state="on", old_state="off"))
        await client._deliver(payload)  # noqa: SLF001

        assert seen == ["sleep_started"], f"включение «мы спим» не дошло до платформы: {seen}"
        assert client.asleep is True

    @pytest.mark.asyncio
    async def test_turning_off_requests_nothing(self) -> None:
        """Выключение модификатора ничего не зажигает — это делает движение.

        Returns:
            Ничего.
        """
        client = _client()
        client.asleep = True
        seen: list[str] = []

        async def on_sleep_started() -> None:
            seen.append("sleep_started")

        client.on_sleep_started = on_sleep_started
        payload = _payload(state_changed_event(MODIFIER, new_state="off", old_state="on"))
        await client._deliver(payload)  # noqa: SLF001

        assert seen == [], f"выключение модификатора породило {seen}"
        assert client.asleep is False

    @pytest.mark.asyncio
    async def test_repeated_on_event_requests_nothing(self) -> None:
        """Повторное событие при уже включённом модификаторе не дублируется.

        Returns:
            Ничего.
        """
        client = _client()
        client.asleep = True
        seen: list[str] = []

        async def on_sleep_started() -> None:
            seen.append("sleep_started")

        client.on_sleep_started = on_sleep_started
        payload = _payload(state_changed_event(MODIFIER, new_state="on", old_state="on"))
        await client._deliver(payload)  # noqa: SLF001

        assert seen == [], f"дублирующее событие {seen}"

    @pytest.mark.asyncio
    async def test_missing_callback_is_not_an_error(self) -> None:
        """Контейнер мог не подключить уведомление — событие не должно ронять поток.

        Returns:
            Ничего.
        """
        client = _client()
        client.asleep = False

        payload = _payload(state_changed_event(MODIFIER, new_state="on", old_state="off"))
        await client._deliver(payload)  # noqa: SLF001

        assert client.asleep is True

    async def test_turning_off_is_visible_in_docker_journal(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Выключение модификатора тоже видно: утром важно, когда «спим» кончилось.

        Returns:
            Ничего.
        """
        import logging

        client = _client()
        client.asleep = True
        payload = _payload(state_changed_event(MODIFIER, new_state="off", old_state="on"))

        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            await client._deliver(payload)  # noqa: SLF001

        assert any("выключился" in record.message for record in caplog.records), (
            "выключение модификатора молчит на INFO — в docker-журнале его не будет"
        )
        assert client._pending_sleep_started is False  # noqa: SLF001

    async def test_turning_on_is_visible_in_docker_journal(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Переключение модификатора обязано быть видно в docker-журнале.

        Адаптер пишет через корневой обработчик stdlib, где INFO не виден
        (урок #70: проверка на INFO молчала и ничего не доказывала). Утренний
        анализ (правило владельца) требует видеть момент, когда свет гасят
        «по спим», — значит запись WARNING.

        Returns:
            Ничего.
        """
        import logging

        client = _client()
        client.asleep = False
        payload = _payload(state_changed_event(MODIFIER, new_state="on", old_state="off"))

        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            await client._deliver(payload)  # noqa: SLF001

        assert any(
            record.levelname == "WARNING" and "включился" in record.message
            for record in caplog.records
        ), "переключение модификатора молчит на INFO: в docker-журнале его не будет"


class TestModifierFlipReachesFlagDrivenAutomata:
    """Смена «мы спим» доходит и до тех, кто решает по флагам дома (2026-10-16).

    Боевой случай: в полночь «мы спим» включился, свет погас — а шторы остались
    открытыми. Автомат штор слушает не ``sleep_started``, а ``settings_changed``;
    сущности модификатора нет в подписке, и без отдельного уведомления шторы о
    смене флага не узнавали вовсе.
    """

    @pytest.mark.asyncio
    async def test_turning_on_reaches_flag_driven_automata(self) -> None:
        """Включение модификатора пересматривает и шторы, а не только свет.

        Returns:
            Ничего.
        """
        client = _client()
        client.asleep = False
        seen: list[str] = []

        async def on_sleep_changed() -> None:
            seen.append("changed")

        client.on_sleep_changed = on_sleep_changed
        payload = _payload(state_changed_event(MODIFIER, new_state="on", old_state="off"))
        await client._deliver(payload)  # noqa: SLF001

        assert seen == ["changed"], f"включение «мы спим» не дошло до штор: {seen}"

    @pytest.mark.asyncio
    async def test_turning_off_reaches_flag_driven_automata(self) -> None:
        """Выключение модификатора утром тоже пересматривает шторы.

        Returns:
            Ничего.
        """
        client = _client()
        client.asleep = True
        seen: list[str] = []

        async def on_sleep_changed() -> None:
            seen.append("changed")

        client.on_sleep_changed = on_sleep_changed
        payload = _payload(state_changed_event(MODIFIER, new_state="off", old_state="on"))
        await client._deliver(payload)  # noqa: SLF001

        assert seen == ["changed"], "утренний пересмотр штор не случился"
