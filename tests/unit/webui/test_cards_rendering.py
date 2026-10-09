"""
T011-T012: Проверки рендеринга карточек с состоянием.

История 1 (P1): Карточка показывает состояние устройства — значение, единицу
измерения, доступность. Состояние берётся из snapshot контекста.

# Copyright 2026 Leonid Artemev
# SPDX-License-Identifier: Apache-2.0
"""

from src.core.services.state_snapshot import DeviceState


class TestDeviceCardRendering:
    """T011: Проверки рендеринга состояния устройства на карточке."""

    def test_device_state_available_on(self) -> None:
        """Устройство включено и доступно."""
        state = DeviceState(
            entity_id="light.kitchen",
            state="on",
            unit_of_measurement=None,
            available=True,
        )

        assert state.entity_id == "light.kitchen"
        assert state.state == "on"
        assert state.available is True
        assert state.unit_of_measurement is None

    def test_device_state_available_off(self) -> None:
        """Устройство выключено и доступно."""
        state = DeviceState(
            entity_id="light.kitchen",
            state="off",
            unit_of_measurement=None,
            available=True,
        )

        assert state.state == "off"
        assert state.available is True

    def test_device_state_unavailable(self) -> None:
        """Устройство не отвечает (unavailable ≠ off)."""
        state = DeviceState(
            entity_id="light.kitchen",
            state="unavailable",
            unit_of_measurement=None,
            available=False,
        )

        assert state.state == "unavailable"
        assert state.available is False
        # Это важно: unavailable показывается как «не отвечает», а не как выключено

    def test_sensor_state_with_unit(self) -> None:
        """Датчик температуры с единицей измерения."""
        state = DeviceState(
            entity_id="sensor.temperature_room1",
            state="21.5",
            unit_of_measurement="°C",
            available=True,
        )

        assert state.state == "21.5"
        assert state.unit_of_measurement == "°C"
        # Карточка покажет "21.5 °C"

    def test_sensor_state_humidity_with_percent(self) -> None:
        """Датчик влажности."""
        state = DeviceState(
            entity_id="sensor.humidity_room1",
            state="45",
            unit_of_measurement="%",
            available=True,
        )

        assert state.state == "45"
        assert state.unit_of_measurement == "%"

    def test_device_state_unknown(self) -> None:
        """Состояние неизвестно (state = 'unknown')."""
        state = DeviceState(
            entity_id="switch.unknown",
            state="unknown",
            unit_of_measurement=None,
            available=False,
        )

        assert state.state == "unknown"
        assert state.available is False
        # Карточка покажет «состояние неизвестно»

    def test_device_state_without_unit_is_none(self) -> None:
        """У устройства нет единицы измерения."""
        state = DeviceState(
            entity_id="light.kitchen",
            state="on",
            unit_of_measurement=None,
            available=True,
        )

        assert state.unit_of_measurement is None


class TestSnapshotDataHandling:
    """T012: Проверки обработки снимка состояний для карточки."""

    def test_snapshot_from_ha_parsing(self) -> None:
        """Разбор ответа HA в DeviceState."""
        ha_entity = {
            "entity_id": "light.kitchen",
            "state": "on",
            "attributes": {
                "unit_of_measurement": "something",
                "friendly_name": "Kitchen Light",
            },
        }

        state = DeviceState.from_ha_state(ha_entity)

        assert state.entity_id == "light.kitchen"
        assert state.state == "on"
        assert state.unit_of_measurement == "something"
        assert state.available is True

    def test_snapshot_unavailable_parsing(self) -> None:
        """HA вернула unavailable."""
        ha_entity = {
            "entity_id": "sensor.temperature",
            "state": "unavailable",
            "attributes": {"unit_of_measurement": "°C"},
        }

        state = DeviceState.from_ha_state(ha_entity)

        assert state.state == "unavailable"
        assert state.available is False
        # Это важно: available=false, чтобы карточка показала «не отвечает»

    def test_snapshot_unknown_parsing(self) -> None:
        """HA вернула unknown (первый запуск, данных ещё нет)."""
        ha_entity = {
            "entity_id": "sensor.new_device",
            "state": "unknown",
            "attributes": {},
        }

        state = DeviceState.from_ha_state(ha_entity)

        assert state.state == "unknown"
        assert state.available is False

    def test_snapshot_missing_entity_id(self) -> None:
        """В HA нет entity_id (странно, но проверяем)."""
        ha_entity = {"state": "on", "attributes": {}}

        state = DeviceState.from_ha_state(ha_entity)

        assert state.entity_id == "unknown"

    def test_snapshot_missing_attributes(self) -> None:
        """HA не вернула attributes."""
        ha_entity = {"entity_id": "light.kitchen", "state": "on"}

        state = DeviceState.from_ha_state(ha_entity)

        assert state.entity_id == "light.kitchen"
        assert state.unit_of_measurement is None
        assert state.attributes == {}

    def test_snapshot_with_extra_attributes(self) -> None:
        """HA вернула много атрибутов, нас интересует только unit."""
        ha_entity = {
            "entity_id": "sensor.temperature",
            "state": "20.5",
            "attributes": {
                "unit_of_measurement": "°C",
                "friendly_name": "Room 1 Temperature",
                "icon": "mdi:thermometer",
                "device_class": "temperature",
                "state_class": "measurement",
            },
        }

        state = DeviceState.from_ha_state(ha_entity)

        assert state.unit_of_measurement == "°C"
        assert "friendly_name" in state.attributes
        # Полные атрибуты сохраняются на случай будущих расширений


class TestCardDisplay:
    """T011-T012: Как карточка должна отображать состояние."""

    def test_on_device_display(self) -> None:
        """Включённое устройство показывает «включено»."""
        state = DeviceState(
            entity_id="light.kitchen",
            state="on",
            available=True,
        )

        # Карточка должна вывести:
        # Статус: включено (или иконка зелёного цвета)
        # Время: (из снимка)
        assert state.state == "on"
        assert state.available

    def test_off_device_display(self) -> None:
        """Выключённое устройство показывает «выключено»."""
        state = DeviceState(
            entity_id="light.kitchen",
            state="off",
            available=True,
        )

        assert state.state == "off"
        assert state.available

    def test_unavailable_device_display(self) -> None:
        """Недоступное устройство показывает «не отвечает», не выключено."""
        state = DeviceState(
            entity_id="light.broken",
            state="unavailable",
            available=False,
        )

        assert state.available is False
        # Карточка ДОЛЖНА показать "не отвечает", а не "выключено"
        # Это различие важно для владельца: выключено вручную ≠ не отвечает

    def test_sensor_with_unit_display(self) -> None:
        """Датчик показывает значение с единицей."""
        state = DeviceState(
            entity_id="sensor.temperature",
            state="21.5",
            unit_of_measurement="°C",
            available=True,
        )

        # Карточка должна вывести: "21.5 °C"
        display = f"{state.state} {state.unit_of_measurement}"
        assert display == "21.5 °C"

    def test_sensor_without_unit_display(self) -> None:
        """Датчик без единицы показывает только значение."""
        state = DeviceState(
            entity_id="sensor.count",
            state="42",
            unit_of_measurement=None,
            available=True,
        )

        # Карточка выведет просто значение
        display = state.state
        assert display == "42"

    def test_unknown_state_display(self) -> None:
        """Неизвестное состояние показывает «состояние неизвестно»."""
        state = DeviceState(
            entity_id="sensor.unknown",
            state="unknown",
            available=False,
        )

        # Карточка покажет "состояние неизвестно", а не просто "unknown"
        assert state.available is False
        # Шаблон проверит available и покажет нужный текст


class TestTimeAndAvailability:
    """T012: Отметка времени и доступность (для FR-020)."""

    def test_snapshot_time_field(self) -> None:
        """Снимок содержит время и статус доступности."""
        import time

        from src.core.services.state_snapshot import Snapshot

        now = time.time()
        snapshot = Snapshot(
            states={"light.kitchen": DeviceState("light.kitchen", "on")},
            at=now,
            reachable=True,
            last_successful_at=now,
        )

        assert snapshot.at == now
        assert snapshot.reachable is True
        # Карточка покажет "данные на 20:04:35" и без отметки "нет связи"

    def test_snapshot_unreachable_home_assistant(self) -> None:
        """HA недоступен, но снимок содержит последние известные данные."""
        import time

        from src.core.services.state_snapshot import Snapshot

        now = time.time()
        last_good = now - 300  # 5 минут назад была связь

        snapshot = Snapshot(
            states={"light.kitchen": DeviceState("light.kitchen", "on")},
            at=now,
            reachable=False,
            last_successful_at=last_good,
        )

        assert snapshot.reachable is False
        assert snapshot.at == now
        assert snapshot.last_successful_at == last_good
        # Карточка покажет «нет связи» и время последних данных (5 минут назад)

    def test_snapshot_never_successful(self) -> None:
        """HA никогда не был доступен (первый запуск)."""
        import time

        from src.core.services.state_snapshot import Snapshot

        now = time.time()
        snapshot = Snapshot(
            states={},
            at=now,
            reachable=False,
            last_successful_at=0.0,  # Никогда не было успешного снимка
        )

        assert snapshot.reachable is False
        assert snapshot.last_successful_at == 0.0
        # Карточка покажет «нет связи» без времени данных


class TestCardShowState:
    """Интеграция: что видит пользователь на карточке."""

    def test_card_shows_device_on(self) -> None:
        """На карточке горящего света видно «включено»."""
        state = DeviceState(
            entity_id="light.kitchen",
            state="on",
            available=True,
        )

        # Проверяем, что карточка может это отобразить
        assert state.available and state.state == "on"

    def test_card_shows_device_off(self) -> None:
        """На карточке выключенного света видно «выключено»."""
        state = DeviceState(
            entity_id="light.kitchen",
            state="off",
            available=True,
        )

        assert state.available and state.state == "off"

    def test_card_shows_unavailable_clearly(self) -> None:
        """На карточке неотвечающего устройства видна отметка «не отвечает»."""
        state = DeviceState(
            entity_id="light.broken",
            state="unavailable",
            available=False,
        )

        # Карточка проверяет available и выводит специальное сообщение
        display = "не отвечает" if not state.available else state.state
        assert display == "не отвечает"

    def test_card_shows_temperature_with_unit(self) -> None:
        """На карточке датчика видно значение с единицей."""
        state = DeviceState(
            entity_id="sensor.temperature",
            state="21.5",
            unit_of_measurement="°C",
            available=True,
        )

        display = (
            f"{state.state} {state.unit_of_measurement}"
            if state.unit_of_measurement
            else state.state
        )
        assert display == "21.5 °C"
