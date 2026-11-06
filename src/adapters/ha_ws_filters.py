"""Entity filtering for the Home Assistant WebSocket client (spec 018, T059).

Extracted from SimpleHAWebSocketClient: deciding which events belong to the
platform, and reading global entities before the filter drops them.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from adapters.ha_constants import _BOOLEAN_ROLES, _NUMERIC_ROLES


logger = logging.getLogger("adapters.ha_websocket")


class HaWsFiltersMixin:
    """Filter Home Assistant events and keep global entity values."""

    _filter_size_last_seen: int
    _filtered_out: int
    asleep: bool | None
    daylight: bool | None
    filtered_entity_ids: tuple[str, ...]
    entity_filter_provider: Any
    sleep_modifier_entity: str | None
    climate_entities: dict[str, str]
    ventilation_entities: dict[str, str]
    lighting_entities: dict[str, str]
    cover_entities: dict[str, str]
    global_fields: dict[str, str]
    on_sleep_started: Any
    on_sleep_changed: Any
    on_sunset: Any
    on_sunrise: Any
    _pending_sleep_started: bool
    _pending_sleep_changed: bool
    _pending_sunset: bool
    _pending_sunrise: bool

    @property
    def filtered_out_count(self) -> int:
        """Сколько событий отброшено фильтром сущностей.

        Returns:
            Счётчик отброшенных событий.
        """
        return self._filtered_out

    def _current_filter(self) -> Sequence[str]:
        """Список сущностей, ради которых стоит разбирать событие.

        Живой провайдер важнее снимка: провайдер перечитывает манифест
        адаптера, поэтому устройство, добавленное после старта, проходит
        фильтр сразу, без переподписки (Known Issue #83). Переподписка и не
        нужна — Home Assistant шлёт все события, ограничение чисто локальное.
        Пустой результат провайдера означает «фильтр выключен», как и пустой
        снимок: с пустым манифестом платформа обязана разбирать всё, а не
        молчать при зелёном /ready.

        Returns:
            Список `entity_id` для проверки; пустой, если фильтр не нужен.
        """
        if self.entity_filter_provider is None:
            return self.filtered_entity_ids
        current = self.entity_filter_provider()
        if len(current) != self._filter_size_last_seen:
            # WARNING: info в этом развёртывании не виден, а тихая смена
            # состава подписки — ровно то, что в бою (Known Issue #83)
            # обнаруживали только слепотой автоматики.
            logger.warning(
                f"HAAdapter: subscription filter changed: "
                f"{self._filter_size_last_seen} -> {len(current)} entities"
            )
            self._filter_size_last_seen = len(current)
        return current

    def global_role(self, entity: str) -> str | None:
        """Роль глобальной сущности по её идентификатору.

        Args:
            entity: Идентификатор сущности.

        Returns:
            Роль либо ``None``, если сущность не глобальная.
        """
        for role, candidate in self.climate_entities.items():
            if candidate == entity:
                return role
        for role, candidate in self.ventilation_entities.items():
            if candidate == entity:
                return role
        for role, candidate in getattr(self, "lighting_entities", {}).items():
            if candidate == entity:
                return role
        for role, candidate in getattr(self, "cover_entities", {}).items():
            if candidate == entity:
                return role
        return None

    def store_global(self, role: str, state: str | None, entity: str) -> None:
        """Положить значение глобальной сущности в поле клиента.

        Args:
            role: Роль сущности.
            state: Прочитанное состояние либо ``None``.
            entity: Идентификатор сущности, для журнала.

        Returns:
            Ничего.
        """
        field = self.global_fields.get(role)
        if field is None:
            logger.warning(
                f"Роль глобальной сущности '{role}' не описана, {entity} прочитан в никуда"
            )
            return
        if state is None:
            # Неизвестное остаётся неизвестным: ноль градусов означал бы «зима»,
            # а False — «модификатор выключен», и решение ушло бы в сторону.
            return
        if role in _BOOLEAN_ROLES:
            if state not in ("on", "off"):
                return
            setattr(self, field, state == "on")
        elif role in _NUMERIC_ROLES:
            try:
                setattr(self, field, float(state))
            except ValueError:
                logger.warning(f"Глобальная сущность {entity} не прочитана как число: {state!r}")
                return
        else:  # pragma: no cover - защита от новой роли без ветки
            logger.warning(f"Роль '{role}' не описана среди читаемых значений")
            return
        # WARNING, а не INFO: INFO клиента в docker-журнале не виден (урок #70),
        # а прочитанные значения — основа решений климата и вентиляции.
        logger.warning(f"HAAdapter: {entity} = {getattr(self, field)}")

    def _accepts(self, payload: dict[str, Any]) -> bool:
        """Относится ли событие к сущностям, ради которых подписались.

        Args:
            payload: Событие от HA.

        Returns:
            True, если событие стоит обрабатывать.
        """
        entity_ids = self._current_filter()
        entity_id = payload.get("entity_id")
        if not entity_id:
            return True
        entity = str(entity_id)
        state = self._new_state(payload)
        # Солнце и модификатор разбираются **до** раннего выхода по фильтру.
        #
        # Прежний порядок выходил сразу при пустом фильтре, а фильтр пуст, когда
        # манифест недоступен или в доме ещё нет ни одного устройства. Тогда
        # платформа молча переставала следить за солнцем и за «мы спим»: вечернее
        # освещение не включалось бы по закату, а свет не гас бы по отбою — и
        # нигде в журнале не было бы ни слова о том, почему.
        # Солнце в фильтр манифеста не входит, но его состояние нужно условию
        # «темно ли»: без него движение включает свет при дневном свете
        # (жалоба владельца 2026-10-09). Событие всё равно приходит — HA шлёт
        # все state_changed, — поэтому состояние снимается здесь, до отбрасывания.
        # Глобальные значения климата и вентиляции разбираются здесь же, до
        # фильтра, по той же причине, что и солнце: их нет в манифесте, а условия
        # читают их из контекста каждого решения. Читать один раз при подключении
        # мало: владелец меняет уставку сам, и без реакции на событие обогрев
        # держался бы на старой цели до перезапуска (FR-001; боевой дефект
        # 2026-10-10 — подняли уставку с 21 до 25, в контексте осталось 21).
        role = self.global_role(entity)
        if role is not None:
            if role == "thermostat":
                # Термостат — источник уставки, но сам в контекст не кладётся:
                # его значение (режим heat/off) условиям не нужно, а цель
                # синхронизатор читает из атрибута сам.
                return True
            if role == "setpoint" and entity.startswith("climate."):
                # Уставка климат-устройства — цель в атрибуте, а не состояние
                # (там режим heat/off). Без этого климат-термостат положил бы в
                # climate_setpoint строку heat — условия обогрева получали бы
                # «данных нет».
                raw = payload.get("new_state")
                attributes = raw.get("attributes") if isinstance(raw, dict) else None
                target = attributes.get("temperature") if isinstance(attributes, dict) else None
                if target is None:
                    # Атрибута нет — неизвестно, а не «цель пропала».
                    return True
                state = str(target)
            self.store_global(role, state, entity)
            return True
        if entity == "sun.sun":
            # В событии new_state — словарь, а не строка: прежнее сравнение со
            # строкой было всегда ложно, и после заката платформа считала день —
            # вечером движение не включало свет (вскрыто живым разбором потока
            # 2026-10-09). Нераспознанное состояние (например, unavailable)
            # прежнее значение не трогает: «нет данных» не должно выглядеть как
            # «светло».
            if state in ("above_horizon", "below_horizon"):
                was_bright = self._state_field(payload, "old_state")
                self.daylight = state == "above_horizon"
                # Смена суток — событие для декоративного света: гирлянда на
                # террасе и ночное освещение включаются по закату, а ночное
                # освещение гаснет по рассвету (требования владельца
                # 2026-10-09). Датчика освещённости в доме нет и он сломан, а
                # солнце Home Assistant публикует всегда.
                #
                # О смене судит `old_state` из самого события, а не наше
                # remembered-поле `daylight`: если состояние солнца не прочитано
                # при подключении (сеть, рестарт), поле пустое, и настоящий
                # закат вечером прошёл бы молча — гирлянда не загорелась бы.
                # Событие с `old_state` = unknown (первое после подключения)
                # сменой не считается: что было до нас, платформа не знает, а
                # выдумывать закат среди ночи — значит включить свет, когда все
                # спят.
                if state == "below_horizon" and was_bright == "above_horizon":
                    self._pending_sunset = True
                elif state == "above_horizon" and was_bright == "below_horizon":
                    self._pending_sunrise = True
        elif entity == self.sleep_modifier_entity and state in ("on", "off"):
            was = self.asleep
            self.asleep = state == "on"
            # off -> on — владелец включил «мы спим»: свет пора гасить.
            # Повторное on уведомление не дублирует. WARNING, а не INFO: INFO
            # адаптера в docker-журнале не виден (корневой обработчик, урок
            # #70), а переключение модификатора — заметное событие утреннего
            # анализа: по нему видно, когда свет гасили и когда перестали.
            turning_on = state == "on" and was is not True
            turning_off = state == "off" and was is True
            if turning_on:
                self._pending_sleep_started = True
            if turning_on or turning_off:
                # Смена нужна не только свету: шторы и вентиляция пересматривают
                # решение по смене флагов дома, а сущности модификатора нет в
                # подписке — фильтр её отбрасывает, и без отдельного уведомления
                # они о смене не узнают вовсе.
                self._pending_sleep_changed = True
                verb = "включился: запрошено событие sleep_started" if turning_on else "выключился"
                logger.warning(f"Модификатор «мы спим» {verb} ({entity})")
        # Пустой фильтр — это «манифест недоступен», а не «событие чужое»:
        # событие пропускается наружу, как и прежде, иначе при сбое манифеста
        # платформа перестала бы видеть вообще всё.
        return entity in entity_ids if entity_ids else True

    @staticmethod
    def _new_state(payload: dict[str, Any]) -> Any:
        """Состояние сущности из события в его настоящей форме.

        Home Assistant шлёт ``new_state`` словарём ``{"entity_id": ..., "state":
        ...}``. Сравнение такого словаря со строкой всегда ложно — на этом
        ошибочно строились и проверка солнца, и чтение модификатора: событие
        «мы спим включился» платформа не видела вообще.

        Args:
            payload: Событие от HA (``event.data``).

        Returns:
            Строка состояния или None, если в событии её нет.
        """
        raw = payload.get("new_state")
        if isinstance(raw, dict):
            return raw.get("state")
        return raw

    @staticmethod
    def _state_field(payload: dict[str, Any], key: str) -> Any:
        """Состояние сущности из события по имени поля.

        Args:
            payload: Событие от HA (`event.data`).
            key: Имя поля: `new_state` или `old_state`.

        Returns:
            Строка состояния или None, если её нет.
        """
        raw = payload.get(key)
        if isinstance(raw, dict):
            return raw.get("state")
        return raw

    def _record_filtered_event(self) -> None:
        """Отброшенное событие учитывается в метрике, а не только в памяти.

        Импорт метрик ленивый, как в ``_record_disconnect`` адаптера:
        импорт на уровне модуля создаёт цикл
        ``app.container → ha_adapter → src.core``.

        Returns:
            Ничего.
        """
        from core.metrics import get_metrics_collector

        get_metrics_collector().record_websocket_filtered_event()
