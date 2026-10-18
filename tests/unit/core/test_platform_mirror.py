"""Проблемы дома видны в Home Assistant — карточка тревог на дашборде (B79).

Дашборд показывает комнаты и приборы, но «что требует внимания» оставалось
только в веб-интерфейсе платформы. Владелец смотрит дом с телефона, поэтому
обход дома публикует свою сводку как сущность Home Assistant через
MQTT-автообнаружение:

* состояние — читаемая строка «что и где» («2: Грядки: Батарея — не отвечает; …»);
* атрибуты — число, время и полный список проблем.

Проверки держат три вещи, на которых легко ошибиться:

1. идентификатор сущности **предсказуем** (`sensor.platforma_problemy_v_dome`):
   на него ссылается генератор дашборда, и «как-нибудь назовётся» здесь не
   годится. Home Assistant собирает идентификатор из имени устройства и имени
   сущности (кириллица транслитерируется), а `object_id` игнорирует — проверено
   живьём 18.10, поэтому пара имён закреплена проверкой;
2. в атрибуты не уезжает весь реестр показаний (`areas`) — это килобайты на
   каждое объявление, а нужен только список проблем;
3. отказ публикации не ломает обход дома (FR-009): он считается и называется.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from typing import Any

import pytest

from core.services.platform_mirror import (
    PLATFORM_PROBLEMS_ENTITY_ID,
    PlatformMirror,
)


class Recorder:
    """Публикатор-двойник: запоминает топики и отвечает «принято» или «нет»."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.published: list[tuple[str, str, bool]] = []

    async def __call__(self, topic: str, payload: str, retain: bool) -> bool:
        """Запомнить публикацию.

        Args:
            topic: Топик MQTT.
            payload: Полезная нагрузка.
            retain: Хранить ли сообщение.

        Returns:
            Принято ли сообщение.
        """
        self.published.append((topic, payload, retain))
        return self.ok


REPORT: dict[str, Any] = {
    "generated_at": "2026-10-18T07:00:00+00:00",
    "sensor_count": 139,
    "problems": [
        {
            "kind": "unavailable",
            "subject": "sensor.0xa4c138ef3971344e_battery",
            "name": "Батарея",
            "area": "Грядки",
            "detail": "Батарея (Грядки): прибор не отвечает",
        },
        {
            "kind": "low_battery",
            "subject": "sensor.datchik_temperatury_terassa_battery",
            "name": "Батарейка",
            "area": "Терраса",
            "detail": "Батарейка (Терраса): 1 %",
        },
    ],
    # Реестр показаний — большой и в атрибуты попадать не должен.
    "areas": {"комната:Гостиная": [{"entity_id": "sensor.x", "value": "21.0"}] * 50},
}


def _payload(recorder: Recorder, suffix: str) -> str:
    """Полезная нагрузка последнего топика с заданным окончанием.

    Args:
        recorder: Запись публикаций.
        suffix: Окончание топика.

    Returns:
        Полезная нагрузка.
    """
    for topic, payload, _ in reversed(recorder.published):
        if topic.endswith(suffix):
            return payload
    raise AssertionError(f"топик с окончанием {suffix!r} не публиковался")


class TestProblemsEntity:
    """Сводка обхода дома публикуется как одна предсказуемая сущность."""

    @pytest.mark.asyncio
    async def test_entity_id_is_stable_for_the_dashboard(self) -> None:
        """Идентификатор и пара имён, из которых он собирается, закреплены.

        Home Assistant игнорирует `object_id` в автообнаружении и собирает
        идентификатор из имени устройства и имени сущности (проверено живьём
        18.10). Генератор дашборда ссылается на результат, поэтому пара имён и
        идентификатор меняются только вместе.
        """
        recorder = Recorder()
        mirror = PlatformMirror(publish=recorder)

        await mirror.publish_report(REPORT)

        config_topic, config_payload, retain = recorder.published[0]
        assert config_topic == "homeassistant/sensor/behavioral_platform_problems/config"
        assert retain is True, "объявление должно переживать перезапуск дома"
        config = json.loads(config_payload)
        assert config["unique_id"] == "behavioral_platform_problems"
        assert config["name"] == "Проблемы в доме"
        assert config["device"]["name"] == "Платформа"
        assert PLATFORM_PROBLEMS_ENTITY_ID == "sensor.platforma_problemy_v_dome", (
            "идентификатор сущности изменился — правьте пару имён и генератор дашборда вместе"
        )

    @pytest.mark.asyncio
    async def test_state_names_the_problems(self) -> None:
        """Состояние — читаемая строка «что и где», а не счётчик."""
        recorder = Recorder()
        mirror = PlatformMirror(publish=recorder)

        await mirror.publish_report(REPORT)

        text = _payload(recorder, "/platform/problems/state")
        assert text.startswith("2: "), text
        assert "Грядки: Батарея — не отвечает" in text
        assert "Терраса: Батарейка — батарейка на исходе" in text

    @pytest.mark.asyncio
    async def test_attributes_name_every_problem(self) -> None:
        """В атрибутах — что именно и где, но не весь реестр показаний."""
        recorder = Recorder()
        mirror = PlatformMirror(publish=recorder)

        await mirror.publish_report(REPORT)

        attributes = json.loads(_payload(recorder, "/platform/problems/attributes"))
        assert attributes["count"] == 2
        assert [item["subject"] for item in attributes["problems"]] == [
            "sensor.0xa4c138ef3971344e_battery",
            "sensor.datchik_temperatury_terassa_battery",
        ]
        assert attributes["problems"][0]["area"] == "Грядки"
        assert "areas" not in attributes, "реестр показаний в атрибуты не уезжает"
        assert attributes["sensor_count"] == 139

    @pytest.mark.asyncio
    async def test_announcement_is_published_once(self) -> None:
        """Объявление — один раз за процесс: повтор стоит вызова и не нужен."""
        recorder = Recorder()
        mirror = PlatformMirror(publish=recorder)

        await mirror.publish_report(REPORT)
        await mirror.publish_report(REPORT)

        configs = [topic for topic, _, _ in recorder.published if topic.endswith("/config")]
        assert configs == ["homeassistant/sensor/behavioral_platform_problems/config"]

    @pytest.mark.asyncio
    async def test_no_problems_says_so(self) -> None:
        """Проблем нет — это «Проблем нет», а не пустое состояние."""
        recorder = Recorder()
        mirror = PlatformMirror(publish=recorder)

        await mirror.publish_report({**REPORT, "problems": []})

        assert _payload(recorder, "/platform/problems/state") == "Проблем нет"


class TestFailuresAreVisibleNotFatal:
    """Отказ публикации считается и называется, но обход не роняет."""

    @pytest.mark.asyncio
    async def test_rejected_publication_is_counted(self) -> None:
        """Дом отверг публикацию — это отказ, а не исключение."""
        recorder = Recorder(ok=False)
        mirror = PlatformMirror(publish=recorder)

        ok = await mirror.publish_report(REPORT)

        assert ok is False
        assert mirror.describe()["failed"] > 0

    @pytest.mark.asyncio
    async def test_exception_is_counted_and_not_raised(self) -> None:
        """Исключение публикатора не должно доходить до обхода дома."""

        async def broken(topic: str, payload: str, retain: bool) -> bool:
            raise RuntimeError("брокер недоступен")

        mirror = PlatformMirror(publish=broken)

        ok = await mirror.publish_report(REPORT)

        assert ok is False
        assert mirror.describe()["failed"] > 0

    @pytest.mark.asyncio
    async def test_disabled_mirror_publishes_nothing(self) -> None:
        """Дом без MQTT: зеркало выключено и молчит."""
        recorder = Recorder()
        mirror = PlatformMirror(publish=recorder, enabled=False)

        ok = await mirror.publish_report(REPORT)

        assert ok is False
        assert recorder.published == []
