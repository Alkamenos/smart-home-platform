"""Глобальная цветовая температура света: день → вечер → ночь.

Владелец хочет один общий свет: днём холодный, после заката плавно теплеет и к
``color_temp_warm_at`` (по умолчанию 21:00) становится максимально тёплым.
Границы «день» и «ночь» живут в Home Assistant (``input_number``), текущее
значение служба пишет в отдельный ``input_number`` — его же читают действия
включения. Горящие лампы получают новое значение сразу, а не ждут следующего
включения.

Почему отдельная служба, а не условие FSM: температура — не решение автомата, а
непрерывная величина. Автомат включается по движению или кнопке, а между
событиями его никто не будит; без службы свет оставался бы на температуре
включения, пока его не выключат.

Общий оттенок — настройка дома, а не спор за состояние: команды идут мимо ручной
блокировки (``bypass_lockout``), иначе после каждого ручного включения лампа
оставалась бы на прошлой температуре целый час. Ночной красный режим при этом не
трогается — служба спрашивает у контейнера, не работает ли лампа ночником.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from core.commands.dispatcher import CommandIntent
from core.services.light_color_curve import (
    DEFAULT_DAY_KELVIN,
    DEFAULT_NIGHT_KELVIN,
    DEFAULT_WARM_AT,
    parse_datetime as _parse_datetime,
    parse_hhmm as _parse_hhmm,
    target_kelvin,
)


#: Как часто обновлять значение, если не задано в манифесте.
DEFAULT_INTERVAL_MINUTES = 5.0

#: Бит ``LightEntityFeature.TRANSITION`` в Home Assistant.
TRANSITION_FEATURE = 32


def _lighting_devices(manifest: Any) -> list[tuple[str, int]]:
    """Лампы, которым положена глобальная температура, и их приоритет.

    Берутся устройства с шаблоном ``lighting`` или ``deco_light`` и явным
    признаком ``use_global_color_temp``. Ночник (красный) и уличный декор без
    этого признака остаются при своих настройках. Приоритет поведения нужен
    команде температуры: с тем же приоритетом она не вытесняет включение/
    выключение света, но и не оказывается ниже уже активного намерения того же
    поведения.

    Args:
        manifest: Манифест дома.

    Returns:
        Список пар «entity_id, приоритет» без повторов.
    """
    devices: list[tuple[str, int]] = []
    seen: set[str] = set()
    for room in getattr(manifest, "rooms", []) or []:
        for device in getattr(room, "devices", []) or []:
            for behavior in getattr(device, "behaviors", []) or []:
                if getattr(behavior, "template", None) not in ("lighting", "deco_light"):
                    continue
                params = getattr(behavior, "params", None) or {}
                if not params.get("use_global_color_temp"):
                    continue
                entity_id = getattr(device, "id", None)
                if entity_id and entity_id not in seen:
                    seen.add(entity_id)
                    devices.append((entity_id, int(getattr(behavior, "priority", 50) or 50)))
    return devices


class LightColorTemperatureService:
    """Считать общую температуру света и обновлять горящие лампы.

    Args:
        adapter: Адаптер Home Assistant: чтение сущностей и запись helper-а.
        dispatcher: Диспетчер команд: через него уходят команды лампам, поэтому
            ручная блокировка и приоритеты работают как у остальной автоматики.
        manifest: Манифест дома с правилами света.
        interval_minutes: Период пересчёта; по умолчанию из манифеста или 5 мин.
        now_supplier: Источник времени; подменяется в тестах.
        night_mode_supplier: Признак «лампа сейчас ночник»; такие лампы не
            трогаем, иначе красный ночной свет станет белым.
    """

    def __init__(
        self,
        adapter: Any,
        dispatcher: Any,
        manifest: Any,
        interval_minutes: float | None = None,
        now_supplier: Callable[[tzinfo], datetime] | None = None,
        night_mode_supplier: Callable[[str], bool] | None = None,
    ) -> None:
        self._adapter = adapter
        self._dispatcher = dispatcher
        self._manifest = manifest
        self._rules = getattr(manifest.automation_rules, "lighting", None)
        configured = getattr(self._rules, "color_temp_update_minutes", None)
        self.interval_minutes = float(interval_minutes or configured or DEFAULT_INTERVAL_MINUTES)
        self._now = now_supplier or (lambda tz: datetime.now(tz))
        self._night_mode_supplier = night_mode_supplier
        self._task: asyncio.Task[None] | None = None

    async def check_once(self) -> None:
        """Пересчитать температуру, записать helper и обновить горящие лампы.

        Returns:
            Ничего.
        """
        target = await self._target_now()
        await self._write_current(target)
        await self._apply_to_lights(target)

    async def _target_now(self) -> int:
        """Актуальная температура для текущего момента.

        Returns:
            Значение в Кельвинах, ограниченное диапазоном helper-а.
        """
        tz = self._timezone()
        now = self._now(tz)
        day_kelvin, night_kelvin = await self._bounds()
        sun = await self._snapshot("sun.sun") or {}
        daylight = self._daylight(sun.get("state"))
        sunset = self._sunset(sun, daylight, tz)
        warm_at = _parse_hhmm(
            getattr(self._rules, "color_temp_warm_at", None) or DEFAULT_WARM_AT, time(21, 0)
        )
        target = target_kelvin(
            now,
            daylight=daylight,
            sunset=sunset,
            day_kelvin=day_kelvin,
            night_kelvin=night_kelvin,
            warm_at=warm_at,
        )
        logger.info(
            f"Цветовая температура света: {target} К "
            f"(день {day_kelvin:g}, ночь {night_kelvin:g}, "
            f"солнце {'над горизонтом' if daylight else 'под горизонтом' if daylight is False else 'неизвестно'})"
        )
        return await self._clamp_to_helper(target)

    def _timezone(self) -> tzinfo:
        """Часовой пояс дома.

        Returns:
            Зона из манифеста либо UTC, если пояс не задан или неизвестен.
        """
        name = getattr(self._manifest.instance, "time_zone", None) or "UTC"
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 — неизвестный пояс не должен ронять свет
            logger.warning(f"Цветовая температура: неизвестный пояс {name!r}, беру UTC")
            return ZoneInfo("UTC")

    async def _bounds(self) -> tuple[float, float]:
        """Прочитать дневную и ночную границы из Home Assistant.

        Returns:
            Пару «день, ночь» в Кельвинах. Недоступная сущность не отменяет
            общий свет: берётся значение по умолчанию.
        """
        day = await self._number(
            getattr(self._rules, "color_temp_day_entity", None), DEFAULT_DAY_KELVIN
        )
        night = await self._number(
            getattr(self._rules, "color_temp_night_entity", None), DEFAULT_NIGHT_KELVIN
        )
        return day, night

    async def _number(self, entity_id: str | None, default: float) -> float:
        """Прочитать числовое значение сущности.

        Args:
            entity_id: Сущность либо ``None``.
            default: Значение при отсутствии/ошибке.

        Returns:
            Число.
        """
        if not entity_id:
            return default
        reader = getattr(self._adapter, "get_entity_state", None)
        if reader is None:
            return default
        try:
            state = await reader(entity_id)
        except Exception as exc:  # noqa: BLE001 — свет важнее диагностики
            logger.warning(f"Цветовая температура: {entity_id} не прочитана: {exc}")
            return default
        if state is None:
            return default
        try:
            return float(state)
        except (TypeError, ValueError):
            return default

    async def _snapshot(self, entity_id: str) -> dict[str, Any] | None:
        """Прочитать снимок сущности, не роняя службу.

        Args:
            entity_id: Сущность.

        Returns:
            Словарь состояния и атрибутов либо ``None``.
        """
        reader = getattr(self._adapter, "get_entity_snapshot", None)
        if reader is None:
            return None
        try:
            snapshot = await reader(entity_id)
        except Exception as exc:  # noqa: BLE001 — неизвестность не повод молчать
            logger.warning(f"Цветовая температура: снимок {entity_id} не прочитан: {exc}")
            return None
        return snapshot if isinstance(snapshot, dict) else None

    @staticmethod
    def _daylight(state: Any) -> bool | None:
        """Перевести состояние ``sun.sun`` в «светло ли».

        Args:
            state: Состояние солнца.

        Returns:
            True/False либо None, если состояние неизвестно.
        """
        if state == "above_horizon":
            return True
        if state == "below_horizon":
            return False
        return None

    @staticmethod
    def _sunset(sun: dict[str, Any], daylight: bool | None, tz: tzinfo) -> datetime | None:
        """Время сегодняшнего заката из атрибутов ``sun.sun``.

        После заката ``next_setting`` — уже завтрашний, поэтому берётся минус
        сутки: это сегодняшний закат (переходов на летнее время в доме нет).
        Днём ``next_setting`` — сегодняшний.

        Args:
            sun: Снимок ``sun.sun``.
            daylight: Светло ли.
            tz: Часовой пояс дома.

        Returns:
            Время заката либо ``None``.
        """
        next_setting = _parse_datetime(sun.get("next_setting"), tz)
        if next_setting is None:
            return None
        # HA отдаёт ``next_setting`` в UTC. Для кривой важен закат **по часам
        # дома**: иначе ``warm_at`` (21:00) строится в UTC, и самое тёплое
        # наступает в 02:00 по дому (боевая находка 29.10).
        next_setting = next_setting.astimezone(tz)
        if daylight is False:
            return next_setting - timedelta(days=1)
        return next_setting

    async def _clamp_to_helper(self, target: int) -> int:
        """Ограничить значение диапазоном helper-а текущей температуры.

        Args:
            target: Рассчитанное значение, К.

        Returns:
            Значение в допустимом диапазоне helper-а.
        """
        entity = getattr(self._rules, "color_temp_current_entity", None)
        if not entity:
            return target
        snapshot = await self._snapshot(entity) or {}
        low = snapshot.get("min")
        high = snapshot.get("max")
        try:
            if low is not None:
                target = max(int(round(float(low))), target)
            if high is not None:
                target = min(int(round(float(high))), target)
        except (TypeError, ValueError):
            pass
        return target

    async def _write_current(self, target: int) -> None:
        """Записать текущую температуру в helper Home Assistant.

        Args:
            target: Значение, К.

        Returns:
            Ничего.
        """
        entity = getattr(self._rules, "color_temp_current_entity", None)
        if not entity:
            return
        snapshot = await self._snapshot(entity) or {}
        current = snapshot.get("state")
        if current is not None:
            try:
                if abs(float(current) - target) < 0.5:
                    return
            except (TypeError, ValueError):
                pass
        try:
            await self._adapter.call_service(
                domain="input_number",
                service="set_value",
                entity_id=entity,
                data={"value": target},
            )
        except Exception as exc:  # noqa: BLE001 — helper не должен ронять свет
            logger.warning(f"Цветовая температура: {entity} не записана: {exc}")

    async def apply_to_device(self, device_id: str) -> None:
        """Сразу применить актуальную температуру к одной лампе.

        Нужно после ручного включения: лампа восстанавливает прошлую
        температуру, а ручная блокировка не должна мешать общему свету дома
        (требование владельца 2026-10-24).

        Args:
            device_id: Лампа, которую только что включили.

        Returns:
            Ничего.
        """
        priority = self._priority_for(device_id)
        if priority is None or self._is_night_mode(device_id):
            return
        snapshot = await self._snapshot(device_id)
        if not snapshot or str(snapshot.get("state")).lower() != "on":
            return
        supported = snapshot.get("supported_color_modes") or []
        if supported and "color_temp" not in supported:
            return
        target = await self._target_now()
        # После ручного включения ждать пять минут нельзя: человек видит
        # прошлую температуру. Короткий переход делает поправку заметной сразу.
        await self._submit(device_id, priority, target, snapshot, transition_sec=5)

    def _priority_for(self, device_id: str) -> int | None:
        """Приоритет поведения для лампы с общей температурой.

        Args:
            device_id: Лампа.

        Returns:
            Приоритет либо ``None``, если лампа не участвует в общей схеме.
        """
        for candidate, priority in _lighting_devices(self._manifest):
            if candidate == device_id:
                return priority
        return None

    def _is_night_mode(self, device_id: str) -> bool:
        """Лампа сейчас работает ночником (её нельзя делать белой).

        Args:
            device_id: Лампа.

        Returns:
            True, если это ночной режим.
        """
        return bool(self._night_mode_supplier and self._night_mode_supplier(device_id))

    async def _apply_to_lights(self, target: int) -> None:
        """Обновить температуру у горящих ламп.

        Args:
            target: Значение, К.

        Returns:
            Ничего.
        """
        for device_id, priority in _lighting_devices(self._manifest):
            if self._is_night_mode(device_id):
                continue
            snapshot = await self._snapshot(device_id)
            if not snapshot or str(snapshot.get("state")).lower() != "on":
                continue
            supported = snapshot.get("supported_color_modes") or []
            if supported and "color_temp" not in supported:
                continue
            if snapshot.get("min_color_temp_kelvin") is None and not supported:
                continue
            await self._submit(device_id, priority, target, snapshot)

    async def _submit(
        self,
        device_id: str,
        priority: int,
        target: int,
        snapshot: dict[str, Any],
        transition_sec: int | None = None,
    ) -> None:
        """Отправить команду температуры.

        Args:
            device_id: Лампа.
            priority: Приоритет поведения.
            target: Значение, К.
            snapshot: Снимок лампы.
            transition_sec: Переход в секундах; по умолчанию период службы.

        Returns:
            Ничего.
        """
        value = self._clamp_lamp(target, snapshot)
        data: dict[str, Any] = {"color_temp_kelvin": value}
        brightness = snapshot.get("brightness")
        if brightness is not None:
            data["brightness"] = brightness
        features = snapshot.get("supported_features")
        if isinstance(features, int) and features & TRANSITION_FEATURE:
            if transition_sec is None:
                transition_sec = int(min(self.interval_minutes * 60.0, 300.0))
            data["transition"] = transition_sec
        intent = CommandIntent(
            device_id=device_id,
            domain="light",
            service="turn_on",
            data=data,
            priority=priority,
            source="light_color_temperature",
            skip_if={"state": "on", "color_temp_kelvin": value},
            conflict_free=True,
            # Общая температура — настройка дома, а не спор за состояние:
            # ручная блокировка не должна оставлять лампу на прошлом оттенке
            # (требование владельца 2026-10-24).
            bypass_lockout=True,
        )
        try:
            await self._dispatcher.submit(intent)
        except Exception as exc:  # noqa: BLE001 — одна лампа не мешает остальным
            logger.warning(f"Цветовая температура: команда {device_id} не ушла: {exc}")

    @staticmethod
    def _clamp_lamp(target: int, snapshot: dict[str, Any]) -> int:
        """Ограничить значение диапазоном конкретной лампы.

        Args:
            target: Значение, К.
            snapshot: Снимок лампы.

        Returns:
            Значение в диапазоне лампы.
        """
        low = snapshot.get("min_color_temp_kelvin")
        high = snapshot.get("max_color_temp_kelvin")
        try:
            if low is not None:
                target = max(int(round(float(low))), target)
            if high is not None:
                target = min(int(round(float(high))), target)
        except (TypeError, ValueError):
            pass
        return target

    async def _run(self) -> None:
        """Пересчитывать температуру до остановки.

        Returns:
            Ничего.
        """
        interval = max(self.interval_minutes, 1.0) * 60.0
        delay = min(60.0, interval)
        while True:
            await asyncio.sleep(delay)
            delay = interval
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — фоновая служба не должна умирать
                logger.warning(f"Цветовая температура не пересчитана: {exc}")

    def start(self) -> None:
        """Запустить службу в фоне.

        Returns:
            Ничего.
        """
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
            logger.info(
                f"Цветовая температура света: обновление каждые {self.interval_minutes:g} мин"
            )

    async def stop(self) -> None:
        """Остановить службу.

        Returns:
            Ничего.
        """
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 — остановка не шумит
                return

    def describe(self) -> dict[str, Any]:
        """Описание службы для журнала и готовности.

        Returns:
            Словарь с периодом и признаком работы.
        """
        return {
            "interval_minutes": self.interval_minutes,
            "running": self._task is not None and not self._task.done(),
        }
