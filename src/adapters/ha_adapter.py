"""
Home Assistant Adapter for Smart Home Platform.

This module provides an adapter for bidirectional communication with Home Assistant,
supporting both Pyscript mode (recommended for simplicity and hot-reload) and
WebSocket mode (for standalone execution outside HA).

Features:
- Dual-mode operation (Pyscript or WebSocket)
- End-to-end trace_id propagation for debugging
- Exponential backoff reconnection for WebSocket mode
- Graceful shutdown with timer cancellation
- Error isolation to prevent FSMEngine crashes
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine, Iterable, Sequence
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

import aiohttp


# Use standard logging instead of loguru for consistency with logging_service
logger = logging.getLogger(__name__)


# Предел ожидания закрытия WebSocket. Закрытие идёт по рукопожатию, и на
# молчащем соединении оно может не прийти вовсе; ждать бесконечно означает
# остановить heartbeat и основной цикл адаптера (#70).
WS_CLOSE_TIMEOUT_SEC = 5.0

#: Сколько ждём ответа HA на подписку.
#:
#: Отдельно от закрытия: подписка не закрывает соединение, но без ответа на неё
#: события не придут, а узнать об этом можно только по отсутствию событий.
#: Константа, а не число в коде, чтобы проверки не ждали десять секунд каждая.
SUBSCRIPTION_TIMEOUT_SEC = 10.0

#: Сколько последних контекстов своих команд помнит адаптер.
#:
#: Идентификаторов ровно столько, сколько команд платформа отправила за
#: последние минуты: у каждой свой, и хранить их вечно незачем. Восемь
#: устройств при переходах каждые несколько секунд дают порядка сотни записей,
#: поэтому 256 — с запасом и без роста памяти.
OWN_CONTEXT_KEEP = 256


@runtime_checkable
class ActionGateProtocol(Protocol):
    """Разрешение на выполнение команд, выходящих в Home Assistant.

    Отдельный протокол, а не конкретный ``DeploymentManager``, потому что адаптер
    не должен зависеть от конкретного класса: запрет на выход — это свойство
    транспорта, а способ переключения режима — свойство политики (#77).
    """

    def should_execute_action(self) -> bool:
        """Вернуть True, если команды разрешено выполнять."""
        ...


class AlwaysExecuteGate:
    """Ворота, пропускающие всё.

    Значение по умолчанию, когда менеджер развёртывания не передан. Обратный
    вариант (блокировать всё) тихо отключил бы автоматику у того, кто забыл
    передать менеджер, и выглядел бы как «свет перестал включаться».
    """

    def should_execute_action(self) -> bool:
        """Всегда разрешать выполнение."""
        return True


class SimpleHAWebSocketClient:
    """Minimal WebSocket client implementing HA WebSocket API protocol.

    HA uses message-based auth:
      1. Client connects
      2. Server sends {"type": "auth_required", ...}
      3. Client sends {"type": "auth", "access_token": "..."}
      4. Server sends {"type": "auth_ok"} or {"type": "auth_invalid"}
    """

    def __init__(self, url: str, token: str, session: Any = None) -> None:
        self.url = url
        self.token = token
        self.session = session
        # Тип соединения определяется локальным импортом ``websockets`` внутри
        # connect(), поэтому имя типа здесь недоступно: атрибут помечается Any.
        # Без аннотации mypy выводил бы None из инициализатора и ругался на
        # каждый .recv()/.send()/.close() (attr-defined).
        self.ws: Any = None
        self.connected = False
        self._msg_id = 0
        self._handlers: dict[int, Callable[..., Any]] = {}
        self._event_handler: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        self._listen_task: asyncio.Task[None] | None = None
        # События обрабатываются отдельной задачей, а не прямо в цикле чтения.
        # Иначе команда, отправленная из обработчика события (любая команда
        # автоматики), ждёт ответа HA в том же цикле, который этот ответ и
        # должен прочитать: чтение блокировано до таймаута. Проверено на живом
        # HA 2026-10-08 — каждая команда стоила 15 с и теряла `context.id`.
        # Очередь сохраняет порядок событий: автоматы зависят от него.
        self._event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._event_worker_task: asyncio.Task[None] | None = None
        # Причина последнего разрыва. Нужна, чтобы отличить молчаливый уход HA
        # от собственной остановки: без неё оба случая выглядят одинаково.
        self._disconnect_reason: str | None = None
        # Подтверждена ли подписка ответом HA. Отправленное сообщение — ещё не
        # подписка: HA может отвергнуть её, и тогда события не придут никогда.
        self.subscription_confirmed: bool = False
        self.subscription_error: str | None = None
        # Сущности, ради которых подписывались. Фильтра на стороне HA нет
        # (проверено на живом HA 2026-10-08: `entity_ids` отвергается как
        # лишний ключ), поэтому ограничение применяется у нас.
        #
        # Список — замороженный снимок на момент subscribe(). Снимок слеп, если
        # манифест меняется после старта: устройство, добавленное через
        # /devices/apply, не получало бы собственных событий до рестарта
        # (Known Issue #83). Поэтому адаптер ставит сюда живой провайдер —
        # он важнее снимка и перечитывает манифест на каждом событии.
        self.filtered_entity_ids: tuple[str, ...] = ()
        self.entity_filter_provider: Callable[[], Sequence[str]] | None = None
        # Идентификатор подписки, ответ на который ещё ожидается. Инициализируется
        # перед вызовом _subscription_result().
        self._pending_subscription_id: int = 0
        # Сколько событий отброшено фильтром сущностей.
        self._filtered_out = 0
        # Спим ли сейчас: True — модификатор «мы спим» включён в Home Assistant.
        # Модификатором управляет владелец: он сам включает и выключает его
        # автоматизацией, а платформа только читает. None — сущности нет.
        self.asleep: bool | None = None
        # Сущность-модификатор; ставится адаптером перед подпиской.
        self.sleep_modifier_entity: str | None = None
        # Имена глобальных сущностей климата и вентиляции: роль → entity_id.
        # Задаются адаптером из правил дома. Клиент держит их, потому что он же
        # фильтрует события подписки, а эти сущности в манифест не входят.
        self.climate_entities: dict[str, str] = {}
        self.ventilation_entities: dict[str, str] = {}
        # Куда класть прочитанное значение: роль → поле этого же клиента.
        self.global_fields: dict[str, str] = dict(GLOBAL_ENTITY_FIELDS)
        # Уведомление платформы о включении «мы спим»: модификатор гасит свет,
        # но событие устройства это не событие устройства — сущность не входит
        # в подписку и фильтр её всегда отбрасывает. Поэтому переключение
        # ловится здесь, в разборе, и доносится отдельным путём в _deliver.
        self.on_sleep_started: Callable[[], Awaitable[None]] | None = None
        # Запрошено ли уведомление; флаг живёт одно событие.
        self._pending_sleep_started = False
        # Смена суток для декоративного света: закат включает вечернее
        # освещение, рассвет его гасит. Тот же путь, что и у модификатора, —
        # солнце вне подписки, и состояние снимается здесь, в разборе.
        self.on_sunset: Callable[[], Awaitable[None]] | None = None
        self.on_sunrise: Callable[[], Awaitable[None]] | None = None
        self._pending_sunset = False
        self._pending_sunrise = False
        # Светло ли сейчас: True — солнце над горизонтом, None — неизвестно.
        # ``sun.sun`` в манифест не входит, но его состояние снимается здесь, до
        # отбрасывания события фильтром: без него условие «темно ли» не знает, что
        # на улице, и движение включает свет при дневном свете (жалоба владельца
        # 2026-10-09).
        self.daylight: bool | None = None
        # Глобальные сущности климата и вентиляции (спека 014). Имена сущностей
        # приходят из правил дома, значения — отсюда. None означает «не прочитано
        # или неизвестно», и это **не** то же, что False или ноль: условия
        # трактуют неизвестное как «решать не на чем», а не как «не зима» и не
        # как «в комнате ноль градусов».
        self.climate_setpoint: float | None = None
        self.comfort_max: float | None = None
        self.is_winter: bool | None = None
        self.climate_enabled: bool | None = None
        self.ac_allowed: bool | None = None
        self.ventilation_on: bool | None = None
        self.airing_on: bool | None = None
        self.exhaust_on: bool | None = None
        self.ventilation_enabled: bool | None = None
        self.outside_temperature: float | None = None
        # Размер фильтра при последнем наблюдении. Нужен, чтобы изменение
        # состава подписки было видно в журнале, а не только в памяти кода.
        self._filter_size_last_seen: int = 0

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
        ``core.container → ha_adapter → src.core``.

        Returns:
            Ничего.
        """
        from core.metrics import get_metrics_collector

        get_metrics_collector().record_websocket_filtered_event()

    async def _deliver(self, payload: dict[str, Any]) -> None:
        """Передать событие обработчику, если оно проходит фильтр.

        Вынесено отдельно, чтобы доставка проверялась напрямую: события в бою
        приходят из сокета, и подмена пути скрыла бы, где именно теряется
        поток.

        Args:
            payload: Событие от HA.

        Returns:
            Ничего.
        """
        accepted = self._accepts(payload)
        # Переключение «мы спим» доносится до платформы до проверки фильтра:
        # сущность модификатора в подписку не входит, фильтр её отбрасывает
        # всегда, а гасить свет по включению модификатора — требование владельца
        # («свет над столом выключается по модификатору», 2026-10-09).
        if self._pending_sleep_started:
            self._pending_sleep_started = False
            notify = self.on_sleep_started
            if notify is not None:
                try:
                    await notify()
                except Exception as exc:  # noqa: BLE001 — отказ уведомления не роняет поток событий
                    logger.warning(f"HAAdapter: sleep_started не доставлен: {exc}")
        # Закат и рассвет — по тому же пути и по той же причине: солнце вне
        # подписки, а вечернему освещению нужно знать о смене суток. Флаг живёт
        # одно событие, поэтому повторная доставка невозможна.
        for pending, callback, name in (
            ("_pending_sunset", self.on_sunset, "sunset"),
            ("_pending_sunrise", self.on_sunrise, "sunrise"),
        ):
            if not getattr(self, pending):
                continue
            setattr(self, pending, False)
            if callback is None:
                continue
            try:
                await callback()
            except Exception as exc:  # noqa: BLE001 — отказ уведомления не роняет поток событий
                logger.warning(f"HAAdapter: {name} не доставлен: {exc}")
        if not accepted:
            self._filtered_out += 1
            self._record_filtered_event()
            return
        if self._event_handler is not None:
            await self._event_handler(payload)

    async def _event_worker(self) -> None:
        """Разбирать очередь событий, пока её читает цикл сокета.

        Отдельная задача нужна для одной простой причины: команда, которую
        автоматика отправляет в ответ на событие, ждёт ответа Home Assistant —
        а ответ читает тот же цикл. Без раздельных задач чтение блокировалось
        до таймаута: в бою это означало 15 секунд задержки на каждое движение
        и потерю `context.id`, по которому своё действие отличается от
        действия человека (живой запуск 2026-10-08).

        Args:
            Ничего.

        Returns:
            Ничего. Задача живёт до отмены.
        """
        while True:
            payload = await self._event_queue.get()
            if payload is None:
                return
            try:
                await self._deliver(payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — одно событие не роняет поток
                logger.warning(f"HAAdapter: ошибка обработки события: {e}")

    async def connect(self) -> None:
        if self.ws is not None:
            await self.close()
            self.ws = None
        self._msg_id = 0
        self._handlers.clear()
        self._event_handler = None
        # Причина прошлого разрыва не должна пережить новое подключение: иначе
        # после успешного восстановления она продолжала бы объяснять то, что
        # давно починено.
        self._disconnect_reason = None
        try:
            import websockets

            self.ws = await websockets.connect(self.url)
            self.connected = True

            raw = await asyncio.wait_for(self.ws.recv(), timeout=15)
            msg = json.loads(raw)
            if msg.get("type") != "auth_required":
                self.connected = False
                raise ConnectionError(f"Expected auth_required, got: {msg}")

            await self.ws.send(
                json.dumps(
                    {
                        "type": "auth",
                        "access_token": self.token,
                    }
                )
            )

            raw = await asyncio.wait_for(self.ws.recv(), timeout=15)
            msg = json.loads(raw)
            if msg.get("type") == "auth_ok":
                logger.info("HAAdapter: WebSocket authenticated successfully")
            else:
                self.connected = False
                raise ConnectionError(f"Auth failed: {msg}")

            self._listen_task = asyncio.create_task(self._listen_loop())
            self._event_worker_task = asyncio.create_task(self._event_worker())

        except Exception as e:
            logger.warning(f"WebSocket connection failed: {e}")
            self.connected = False

    async def _listen_loop(self) -> None:
        """Читать события, пока соединение живо.

        Флаг ``connected`` сбрасывается в ``finally``, а не в ``except``.
        Home Assistant закрывает соединение штатно (``CLOSE 1001 going away``),
        и цикл чтения при этом доходит до конца **без исключения**: проверено
        на websockets 17.1 и 17.2. Прежний код трогал флаг только в ``except``,
        поэтому после штатного разрыва клиент оставался «подключённым» — и
        ``/ready`` отвечал ``home_assistant: ok``, хотя ни одного события
        больше не пришло бы. Наблюдалось в бою 2026-10-07 пять часов подряд.
        """
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                    msg_type = msg.get("type")

                    if msg_type == "event" and self._event_handler:
                        event_data = msg.get("event", {})
                        payload = event_data.get("data", event_data)
                        # Контекст события лежит в конверте — рядом с `data`,
                        # а не внутри (снято с живого HA 2026-10-08:
                        # `event = {event_type, data, context, ...}`).
                        # Раньше в обработчик уходило только `data`, и
                        # `user_id` не доходил до record_manual_control:
                        # ручная блокировка не включалась ни одним путём из
                        # дома, хотя сами тесты #18 проходили — они собирали
                        # сообщение с контекстом руками.
                        if (
                            isinstance(payload, dict)
                            and "context" in event_data
                            and "context" not in payload
                        ):
                            payload = {**payload, "context": event_data["context"]}
                        # В очередь, а не сразу в обработчик: чтение сокета не
                        # должно ждать обработку события, иначе команда из
                        # обработчика блокирует чтение ответа на неё самой.
                        self._event_queue.put_nowait(payload)

                    elif msg_type == "result":
                        msg_id = msg.get("id")
                        if msg_id in self._handlers:
                            handler = self._handlers.pop(msg_id)
                            handler(msg)

                except Exception as e:
                    logger.warning(f"HAAdapter: error processing WS message: {e}")
        except Exception as e:
            self._disconnect_reason = f"{type(e).__name__}: {e}"
            logger.warning(f"HAAdapter: listen loop terminated: {e}")
        else:
            # Штатное закрытие: HA ушёл молча, без ошибки. Причина записывается
            # явно, иначе по журналу это неотличимо от «мы отключились сами».
            self._disconnect_reason = f"соединение закрыто сервером: {self.ws.close_code}"
        finally:
            self.connected = False
            logger.warning(f"HAAdapter: listen loop finished ({self._disconnect_reason})")

    async def close(self) -> None:
        # Инструментация #70: heartbeat входит в close() и не возвращается. Чтобы
        # сказать, на каком именно ожидании встали, нужна запись ДО и ПОСЛЕ каждого
        # шага, а не только вход и выход. Уровень WARNING — логи клиента наследуют
        # корневой обработчик, где INFO не виден (проверено: от этого модуля в
        # журнале не было ни одной строки).
        logger.warning(f"HAAdapter: close() start, listen_task={self._listen_task!r}")
        if self._listen_task:
            self._listen_task.cancel()
            logger.warning(f"HAAdapter: close() cancel sent, task done={self._listen_task.done()}")
            if self._event_worker_task:
                self._event_worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task
            logger.warning(
                f"HAAdapter: close() listen_task awaited, done={self._listen_task.done()}"
            )
        else:
            logger.warning("HAAdapter: close() no listen_task")
        if self.ws:
            logger.warning("HAAdapter: close() closing websocket")
            # Закрытие ограничено по времени (#70). Библиотека ждёт рукопожатия
            # закрытия, которого на молчащем соединении не приходит, и `close()`
            # не возвращался никогда: heartbeat застревал здесь, сокет оставался
            # открытым, переподключения не происходило, а /ready отвечал 200.
            # Известно живьём: второй вызов close() на том же сокете закрывал его
            # за 46 мс, а первый не возвращался совсем.
            try:
                await asyncio.wait_for(self.ws.close(), timeout=WS_CLOSE_TIMEOUT_SEC)
                logger.warning("HAAdapter: close() websocket closed")
            except TimeoutError:
                # Таймаут — не повод молчать: закрытие не завершилось, и это
                # единственный признак, по которому висяние видно в журнале.
                logger.warning(
                    f"HAAdapter: close() websocket close timed out after "
                    f"{WS_CLOSE_TIMEOUT_SEC}s, continuing anyway"
                )
            except Exception as error:  # noqa: BLE001 — закрытие не должно ронять heartbeat
                logger.warning(f"HAAdapter: close() websocket close failed: {error}")
        self.connected = False

    async def subscribe(
        self,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
        filter_dict: dict[str, Any],
    ) -> None:
        """Подписаться на события Home Assistant.

        Args:
            handler: Обработчик входящего события.
            filter_dict: Фильтр подписки. Поле ``type`` обязательно, поле
                ``entity_ids`` ограничивает список присылаемых сущностей.
        """
        if self.ws and self.connected:
            self._msg_id += 1
            self._event_handler = handler
            sub_msg: dict[str, Any] = {
                "id": self._msg_id,
                "type": "subscribe_events",
                "event_type": filter_dict.get("type", ""),
            }
            # Списка сущностей в API Home Assistant нет. Проверено на живом HA
            # 2026-10-08 пятью вариантами подписки: принимаются `event_type`
            # и `event_id`, а `entity_ids` и даже `entity_id` отвергаются с
            # `extra keys not allowed`. Прежний код отправлял `entity_ids`,
            # HA отвергал подписку, а платформа писала в журнал «subscribed» и
            # ждала событий, которых не могло быть: `/ready` зелёный, доставки
            # нет. Тот же класс, что #9.
            #
            # Поэтому фильтр применяется у нас: подписка идёт на все события,
            # а лишние отбрасываются на входе. Отброшенные считаются — иначе
            # «приходят все 1502» снова станет невидимым.
            entity_ids = tuple(filter_dict.get("entity_ids") or ())
            self.filtered_entity_ids = entity_ids
            # Отсчёт для лога изменений фильтра начинается со снимка подписки:
            # первая смена состава манифеста будет видна как «N -> M», а не
            # как «0 -> M» с потерей исходной точки.
            self._filter_size_last_seen = len(entity_ids)

            self.subscription_confirmed = False
            self.subscription_error = None
            self._pending_subscription_id = self._msg_id

            await self.ws.send(json.dumps(sub_msg))

            try:
                await asyncio.wait_for(
                    self._subscription_result(),
                    timeout=SUBSCRIPTION_TIMEOUT_SEC,
                )
            except TimeoutError:
                self.subscription_error = (
                    f"HA не ответил на подписку за {SUBSCRIPTION_TIMEOUT_SEC:g} с"
                )
                logger.warning(
                    f"HAAdapter: подписка на {sub_msg['event_type']!r} не "
                    f"подтверждена ({self.subscription_error}) — события могут "
                    f"не приходить"
                )

    async def _subscription_result(self) -> None:
        """Дождаться ответа HA на подписку и запомнить, принял ли он её.

        Returns:
            Ничего.
        """
        message = await self._request_result(self._pending_subscription_id)
        if message.get("success") is True:
            self.subscription_confirmed = True
            logger.warning(
                f"HAAdapter: подписка на события подтверждена HA, "
                f"ограничение по сущностям применяется на нашей стороне "
                f"({len(self.filtered_entity_ids)} шт.)"
            )
            return

        error = message.get("error") or {}
        reason = f"{error.get('code', 'unknown')}: {error.get('message', 'без пояснения')}"
        self.subscription_error = reason
        logger.warning(f"HAAdapter: HA отверг подписку ({reason})")

    async def _request_result(self, msg_id: int) -> dict[str, Any]:
        """Дождаться ответа HA на запрос с указанным идентификатором.

        Args:
            msg_id: Идентификатор запроса.

        Returns:
            Ответ HA целиком: ``success``, ``result`` либо ``error``.
        """
        loop = asyncio.get_running_loop()
        result_future: asyncio.Future[Any] = loop.create_future()

        def on_result(msg: dict[str, Any]) -> None:
            if not result_future.done():
                result_future.set_result(msg)

        self._handlers[msg_id] = on_result
        try:
            response = await result_future
        finally:
            self._handlers.pop(msg_id, None)
        return response

    async def get_states(self) -> Any:
        if not self.ws or not self.connected:
            return []

        self._msg_id += 1
        msg_id = self._msg_id

        await self.ws.send(
            json.dumps(
                {
                    "id": msg_id,
                    "type": "get_states",
                }
            )
        )

        try:
            response = await asyncio.wait_for(self._request_result(msg_id), timeout=15)
            return response.get("result", [])
        except TimeoutError:
            return []

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
        return_response: bool = True,
    ) -> Any:
        if not self.ws or not self.connected:
            return None

        self._msg_id += 1
        msg_id = self._msg_id

        payload = {
            "id": msg_id,
            "type": "call_service",
            "domain": domain,
            "service": service,
            "service_data": service_data or {},
        }

        if return_response:
            loop = asyncio.get_event_loop()
            result_future: asyncio.Future[Any] = loop.create_future()

            def on_result(msg: dict[str, Any]) -> None:
                if not result_future.done():
                    result_future.set_result(msg)

            self._handlers[msg_id] = on_result
            await self.ws.send(json.dumps(payload))

            try:
                response = await asyncio.wait_for(result_future, timeout=15)
                return response.get("result")
            except TimeoutError:
                return None
        else:
            await self.ws.send(json.dumps(payload))
            return None


# Always use SimpleHAWebSocketClient (no external dependency)
HAS_WS_LIBRARY = True
# Псевдоним класса для читаемости аннотаций; присваивание само по себе
# корректно, поэтому подавлять здесь нечего (прежний ``# type: ignore`` был
# лишним — mypy сообщал unused-ignore).
HomeAssistantWS = SimpleHAWebSocketClient


if TYPE_CHECKING:
    from core.commands.middleware import ManualLockoutMiddleware
    from core.events.event_router import EventRouter


#: Роли глобальных сущностей климата и вентиляции и поле клиента, которое они
#: заполняют. Ключ роли совпадает с ключом в правилах дома
#: (``automation_rules.climate`` / ``.ventilation``), значение — с полем, которое
#: читает условие.
#:
#: Отдельная таблица, а не разбор имени: читаемость важнее экономии строки, а
#: при несовпадении имён тест укажет на конкретное место.
GLOBAL_ENTITY_FIELDS: dict[str, str] = {
    "setpoint": "climate_setpoint",
    "comfort_max": "comfort_max",
    "season": "is_winter",
    "feature": "climate_enabled",
    "ac_gate": "ac_allowed",
    "enable": "ventilation_on",
    "airing": "airing_on",
    "exhaust": "exhaust_on",
    "ventilation_feature": "ventilation_enabled",
    "outside_temp": "outside_temperature",
}

#: Сущности, значение которых — булево: ``on``/``off`` из Home Assistant.
_BOOLEAN_ROLES = frozenset(
    {"season", "feature", "ac_gate", "enable", "airing", "exhaust", "ventilation_feature"}
)

#: Сущности, значение которых — число: ``number.*`` и ``sensor.*`` температуры.
_NUMERIC_ROLES = frozenset({"setpoint", "comfort_max", "outside_temp"})


class HAAdapter:
    """
    Adapter for bidirectional communication with Home Assistant.

    Supports two modes of operation:
    1. Pyscript mode: Provides wrapper functions called from Pyscript files in HA.
    2. WebSocket mode: Uses aiohttp and homeassistant-websocket library for
       standalone execution outside HA.
    """

    def __init__(
        self,
        mode: str = "pyscript",
        engine: Any | None = None,
        hass: Any | None = None,
        ws_url: str | None = None,
        token: str | None = None,
        manual_lockout_middleware: ManualLockoutMiddleware | None = None,
        event_router: EventRouter | None = None,
        deployment: ActionGateProtocol | None = None,
    ) -> None:
        if mode not in ("pyscript", "websocket"):
            raise ValueError(f"Invalid mode: {mode}. Must be 'pyscript' or 'websocket'")

        self._mode = mode
        self._engine = engine
        self._hass = hass
        self._ws_url = ws_url
        self._token = token
        # Запрет на выход в Home Assistant. Передаётся из Container.build(),
        # иначе переменная SHADOW_MODE оставалась бы объявленной, но не
        # действующей (Known Issue #77).
        self._deployment: ActionGateProtocol = (
            deployment if deployment is not None else AlwaysExecuteGate()
        )

        self._manual_lockout_middleware = manual_lockout_middleware
        self._event_router = event_router
        # Сущность Home Assistant «мы спим»; задаётся правилами освещения в
        # манифесте. Значение читает служба суточного цикла при старте.
        self.sleep_modifier_entity: str | None = None
        # Сущности глобальных значений климата и вентиляции: роль → entity_id.
        # Задаются контейнером из правил дома и читаются при подключении, иначе
        # до первого события платформа не знает ни уставки, ни сезона.
        self.climate_entities: dict[str, str] = {}
        self.ventilation_entities: dict[str, str] = {}
        # Уведомление о включении «мы спим»: контейнер ставит сюда свою
        # функцию, адаптер отдаёт её клиенту в момент чтения модификатора —
        # как только сущность стала известна, клиент начинает ловить её
        # переключения и присылает событие sleep_started.
        self.on_sleep_started: Callable[[], Awaitable[None]] | None = None
        # Уведомления о смене суток для декоративного света. Ставятся
        # контейнером так же, как on_sleep_started: без них событие заката или
        # рассвета никто не услышит, и вечернее освещение не включится.
        self.on_sunset: Callable[[], Awaitable[None]] | None = None
        self.on_sunrise: Callable[[], Awaitable[None]] | None = None
        # Контексты команд, которые отправила сама платформа. Home Assistant
        # возвращает `context.id` на каждый вызов сервиса, и изменение состояния
        # несёт тот же идентификатор: по нему собственная команда отличается от
        # действия человека. Без этого первая же автоматическая команда
        # возвращалась в адаптер как ручное действие (HA ставит `user_id`
        # владельца токена) и включала блокировку против самой себя на 60 минут
        # — вскрыто первым живым запуском 2026-10-08.
        self._own_context_ids: deque[str] = deque(maxlen=OWN_CONTEXT_KEEP)
        # Единицы измерения сущностей, прочитанные у Home Assistant. Боевой
        # дефект 2026-10-11: таймер обогревателя измеряется в секундах, а
        # платформа отправляла минуты — обогрев не работал сутки, и ни один
        # признак (сторож, метрики, состояния автоматов) этого не показывал.
        # Единица нужна на пути действия, то есть на каждом решении, поэтому она
        # читается один раз и хранится здесь, а не запрашивается из действия.
        self._entity_units: dict[str, str] = {}
        # Таймеры обогревателей из манифеста: их единицы измерения нужно знать
        # до первого решения, иначе первое же включение уйдёт с угаданной
        # величиной (боевой дефект 2026-10-11).
        self.heater_timers: list[str] = []
        self._ws_client: HomeAssistantWS | None = None
        self._session: aiohttp.ClientSession | None = None
        # Манифест для фильтра подписки. Не передаётся в __init__, чтобы не
        # менять его подпись: список сущностей нужен только при подписке, а
        # манифест меняется при hot-reload, и копия в адаптере разошлась бы с
        # реальной. Читается через getattr, поэтому адаптер, собранный без
        # манифеста (тесты, локальный запуск), работает как раньше.
        self._manifest: Any = None
        self._shutdown_event = asyncio.Event()
        self._reconnect_task: asyncio.Task[None] | None = None
        self._reconnect_attempt = 0
        self._connected_once = False
        # Причина последнего обрыва живёт на адаптере, а не на клиенте:
        # cleanup обнуляет `_ws_client`, а каждая попытка восстановления
        # создаёт нового клиента с пустой причиной — на клиенте она не
        # доживала бы до `/ready` (живой обрыв 2026-10-08, B29: 20 сэмплов
        # `/ready` подряд без единой причины). Хранение «первой причины»:
        # пока идут неудачные попытки подключения, оператору важнее
        # первопричина обрыва, чем симптом каждой попытки. Сбрасывается
        # при успешном подключении, чтобы новый обрыв не объяснялся
        # причиной старого.
        self._last_disconnect_reason: str | None = None
        self._trace_callbacks: list[
            Callable[[str, str, str, dict[str, Any]], Coroutine[Any, Any, None]]
        ] = []

        if mode == "pyscript" and hass is None:
            raise ValueError("hass instance is required for pyscript mode")
        if mode == "websocket":
            if ws_url is None:
                raise ValueError("ws_url is required for websocket mode")
            if token is None:
                raise ValueError("token is required for websocket mode")

        logger.info(f"HAAdapter initialized in '{mode}' mode")

    def set_fsm_engine(self, engine: Any) -> None:
        """Set the FSM engine reference (called by Container.build())."""
        self._fsm_engine = engine

    def _generate_trace_id(self) -> str:
        return str(uuid.uuid4())[:8]

    def _get_logger(self, trace_id: str) -> logging.LoggerAdapter[logging.Logger]:
        """Get a logger with trace_id context."""
        return logging.LoggerAdapter(logger, {"trace_id": trace_id})

    def remember_entity_unit(self, entity_id: str, unit: Any) -> None:
        """Запомнить единицу измерения сущности, прочитанную у устройства.

        Args:
            entity_id: Сущность Home Assistant.
            unit: Единица измерения из атрибутов состояния (``unit_of_measurement``).

        Returns:
            Ничего.
        """
        if isinstance(unit, str) and unit.strip():
            self._entity_units[entity_id] = unit.strip()

    def get_entity_unit(self, entity_id: str) -> str | None:
        """Единица измерения сущности, если она была прочитана.

        Args:
            entity_id: Сущность Home Assistant.

        Returns:
            Единица измерения либо ``None``, если сущность не наблюдалась или
            устройство единицу не назвало.
        """
        return self._entity_units.get(entity_id)

    async def refresh_entity_units(self, entity_ids: Iterable[str]) -> int:
        """Прочитать единицы измерения таймеров и запомнить их.

        Единица нужна, чтобы команда обогревателю попала в ту величину, которой
        измеряет устройство. Раньше платформа отправляла минуты в таймер,
        измеряемый в секундах: Home Assistant принимала значение, обогреватель
        включался и гас через 15 секунд, а автомат честно отрабатывал свой
        таймер — обогрев не работал сутки без единого признака.

        Args:
            entity_ids: Сущности, единицу которых нужно знать (таймеры).

        Returns:
            Сколько сущностей удалось прочитать.
        """
        if self._session is None or not self._token:
            return 0

        http_url = cast(str, self._ws_url)
        base = http_url.replace("wss://", "https://").replace("ws://", "http://")
        base = base.split("/api/websocket")[0].rstrip("/")
        learned = 0
        for entity_id in entity_ids:
            try:
                async with self._session.get(
                    f"{base}/api/states/{entity_id}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            f"HAAdapter: единица измерения {entity_id} не прочитана "
                            f"(HTTP {response.status}) — таймер получит длительность "
                            "в минутах, а если он в секундах, обогреватель выключится "
                            "почти сразу"
                        )
                        continue
                    payload = await response.json()
            except (TimeoutError, aiohttp.ClientError, ValueError) as error:
                logger.warning(f"HAAdapter: единица измерения {entity_id} не прочитана: {error}")
                continue

            attributes = payload.get("attributes") or {}
            unit = attributes.get("unit_of_measurement")
            if isinstance(unit, str) and unit.strip():
                self.remember_entity_unit(entity_id, unit)
                learned += 1
            else:
                logger.warning(
                    f"HAAdapter: {entity_id} не называет единицу измерения — приняты минуты"
                )

        if learned:
            logger.info(f"HAAdapter: единицы измерения прочитаны для {learned} сущностей")
        return learned

    async def on_state_change(
        self,
        entity_id: str,
        new_state: str,
        old_state: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        context = context or {}

        user_id = context.get("user_id")
        # Собственная команда платформы возвращается из Home Assistant с тем же
        # `user_id`, что и действия из приложения, и без этой проверки
        # засчитывалась бы ручным действием: первая же автоматическая команда
        # включала блокировку против самой себя (живой запуск 2026-10-08).
        own_action = self._is_own_context(context.get("ha_context_id"))
        if user_id and self._manual_lockout_middleware and not own_action:
            self._manual_lockout_middleware.record_manual_control(entity_id)
        elif own_action:
            logger.debug(
                f"HAAdapter: изменение {entity_id} вызвано командой платформы, "
                f"ручным действием не считается"
            )

        trace_id = context.get("trace_id") or self._generate_trace_id()
        log = self._get_logger(trace_id)

        log.info(
            f"HAAdapter: state_change received for {entity_id}: '{old_state}' -> '{new_state}'"
        )

        payload = {
            "entity_id": entity_id,
            "new_state": new_state,
            "old_state": old_state,
            "context": {**context, "trace_id": trace_id},
        }

        # Доставка событий подписчикам идёт через шину платформы — ту же, что
        # использует движок (R-07). Раньше здесь стояло
        # `if hasattr(self._engine, "event_bus")`, и на настоящем `FSMEngine`
        # проверка давала False: шина называлась `_event_bus`, публичного
        # доступа к ней не было. Ветка публикации оказывалась мёртвой, а
        # работала запасная — `engine.trigger()` по идентификатору сущности
        # Home Assistant, который не является именем автомата, поэтому каждое
        # изменение состояния давало отказ `unknown_entity`, а состояние
        # устройства обновляла только ручная синхронизация (#9).
        #
        # Запасной ветки больше нет: подменять доставку вызовом движка нельзя,
        # а если шины нет, публиковать некуда и это не ошибка (тесты, локальный
        # запуск без шины).
        bus = getattr(self._engine, "event_bus", None)
        if bus is not None:
            try:
                await bus.publish(
                    event_type="state_change",
                    payload=payload,
                    trace_id=trace_id,
                )
            except Exception as e:
                log.error(f"HAAdapter: failed to publish event to EventBus: {e}")

        if self._event_router is not None:
            try:
                await self._event_router.route_state_change(
                    entity_id=entity_id,
                    new_state=new_state,
                    old_state=old_state,
                    context=context,
                )
            except Exception as e:
                log.error(f"HAAdapter: EventRouter.route_state_change failed for {entity_id}: {e}")

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        data = data or {}
        trace_id = trace_id or self._generate_trace_id()
        log = self._get_logger(trace_id)

        # Запрет на выход в Home Assistant. Стоит в единственной точке, откуда
        # платформа обращается к HA-сервисам: сюда попадают и команды автоматов
        # (через CommandDispatcher), и ручные команды из WebUI (через
        # DeviceService), причём разными способами вызова. Проверка на уровне
        # вызывающего кода обошла бы один из путей (Known Issue #77).
        if not self._deployment.should_execute_action():
            # WARNING, а не INFO: логи адаптера наследуют корневой обработчик,
            # где info не виден — на info проверка молчала бы и не доказала бы
            # ничего (урок #70). Уровень записей проверяется кодом.
            log.warning(
                f"[DRY RUN] Would execute: {domain}.{service}(entity_id={entity_id}, data={data})"
            )
            # Возвращается True намеренно: в режиме тени автомат продолжает
            # считать свои состояния, иначе нечего было бы наблюдать. Ответ,
            # которого на самом деле нет, и не должен выглядеть как отказ.
            return True

        log.info(f"HAAdapter: calling service {domain}.{service} for {entity_id}")

        try:
            if self._mode == "pyscript":
                return await self._call_service_pyscript(domain, service, entity_id, data, log)
            else:
                return await self._call_service_websocket(domain, service, entity_id, data, log)
        except Exception as e:
            log.error(f"HAAdapter: service call failed {domain}.{service} for {entity_id}: {e}")
            return False

    async def _call_service_pyscript(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any],
        log: Any,
    ) -> bool:
        if self._hass is None:
            log.error("HAAdapter: hass instance not available in pyscript mode")
            return False

        service_data = {**data, "entity_id": entity_id}

        try:
            await self._hass.services.async_call(
                domain=domain,
                service=service,
                service_data=service_data,
            )
            return True
        except Exception as e:
            log.error(f"HAAdapter: pyscript service call error: {e}")
            return False

    def _remember_own_context(self, result: Any) -> None:
        """Запомнить контекст только что отправленной команды.

        Args:
            result: Ответ Home Assistant на вызов сервиса.
        """
        if not isinstance(result, dict):
            return
        context = result.get("context")
        if not isinstance(context, dict):
            return
        context_id = context.get("id")
        if isinstance(context_id, str) and context_id:
            self._own_context_ids.append(context_id)

    def _is_own_context(self, context_id: Any) -> bool:
        """Событие вызвано нашей командой или пришло извне.

        Args:
            context_id: Идентификатор контекста из события Home Assistant.

        Returns:
            True, если событие порождено командой платформы.
        """
        return isinstance(context_id, str) and context_id in self._own_context_ids

    async def _call_service_websocket(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any],
        log: Any,
    ) -> bool:
        if self._ws_client is None:
            log.error("HAAdapter: WebSocket client not connected")
            return False

        service_data = {**data, "entity_id": entity_id}

        try:
            # Ответ запрашивается именно ради `context.id`: без него собственную
            # команду не отличить от действия человека, и блокировка включается
            # против самой платформы (живой запуск 2026-10-08).
            result = await self._ws_client.call_service(
                domain=domain,
                service=service,
                service_data=service_data,
                return_response=True,
            )
            self._remember_own_context(result)
            return True
        except Exception as e:
            log.error(f"HAAdapter: WebSocket service call error: {e}")
            return False

    async def start(self) -> None:
        """Start the adapter (WebSocket mode only).

        KEEPS: starts WebSocket connection as a BACKGROUND TASK so it does not
        block the caller. The caller can then poll ``is_connected`` to check
        progress.
        """
        if self._mode == "pyscript":
            logger.info("HAAdapter: start() is a no-op in pyscript mode")
            return

        if self._mode == "websocket":
            # Launch connection loop as a background task (non-blocking)
            self._reconnect_task = asyncio.create_task(self._connect_websocket())

    def _record_disconnect(self, reason: str, delay: float) -> None:
        """Зафиксировать потерю соединения: причина + метрика + лог.

        Инкрементирует ``websocket_disconnects_total`` и пишет WARNING только
        при реально установленном ранее соединении (``_connected_once``);
        неудачные попытки первичного подключения метрикой не считаются.
        Импорт метрик ленивый: импорт на уровне модуля создаёт цикл
        ``core.container → ha_adapter → src.core``.

        Причина запоминается **до** всякой проверки и на стороне адаптера:
        cleanup обнуляет клиента, а ретраи создают нового, поэтому на
        клиенте причина не доживает до наблюдателя (B29, живой обрыв
        2026-10-08). Если у клиента есть собственная первопричина
        (``_disconnect_reason``, записанная listen loop), она важнее
        обобщённой классификации: исключение цикл чтения проглатывает,
        и классификация видит только «listen task ended».

        Args:
            reason: Причина обрыва (для лога), если у клиента своей нет.
            delay: Задержка перед следующей попыткой восстановления, сек.
        """
        from core.metrics import get_metrics_collector

        client_reason = getattr(self._ws_client, "_disconnect_reason", None)
        effective_reason = client_reason or reason
        if getattr(self, "_last_disconnect_reason", None) is None:
            self._last_disconnect_reason = effective_reason

        self._reconnect_attempt += 1
        if not self._connected_once:
            return
        self._connected_once = False
        get_metrics_collector().record_websocket_disconnect()
        logger.warning(
            f"HAAdapter: WebSocket lost ({effective_reason}), "
            f"reconnecting (attempt {self._reconnect_attempt}, delay {delay:.1f}s)..."
        )

    def _mark_connection_established(self) -> None:
        """Обновить состояние после успешного подключения и подписки.

        Отдельный метод, а не три присвоения в цикле переподключения,
        потому что сброс причины — условие корректности хранения
        «первой причины»: без него следующий обрыв объяснялся бы
        причиной прошлого, и оператор принял бы старый инцидент за новый.

        Returns:
            Ничего.
        """
        self._reconnect_attempt = 0
        self._connected_once = True
        self._last_disconnect_reason = None

    async def _refresh_sleep_modifier(self) -> None:
        """Прочитать состояние «мы спим» при подключении.

        Модификатором управляет владелец в Home Assistant: он включает его
        автоматизацией на ночь и выключает утром. Платформа только читает
        состояние — и обязана прочитать его сразу, иначе до первого события от
        этой сущности дом решит, что все спят (или что никто не спит).

        Args:
            Ничего.

        Returns:
            Ничего. Отсутствие сущности — не ошибка: правила описывают дом, где
            модификатора может не быть.
        """
        entity = self.sleep_modifier_entity
        client = self._ws_client
        session = self._session
        if not entity or client is None or session is None:
            return
        # Клиенту сущность нужна до самой подписки: он следит за её состоянием
        # в потоке событий, и без имени фильтр её просто пропустит.
        client.sleep_modifier_entity = entity
        # И уведомление — вместе с именем: как только клиент знает сущность, он
        # начинает ловить её переключения и шлёт sleep_started платформе.
        client.on_sleep_started = self.on_sleep_started
        http_url = cast(str, self._ws_url)
        base = http_url.replace("wss://", "https://").replace("ws://", "http://")
        url = f"{base.split('/api/websocket')[0].rstrip('/')}/api/states/{entity}"
        try:
            async with session.get(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    logger.warning(
                        f"Модификатор «{entity}» не прочитан: Home Assistant "
                        f"ответил {response.status}"
                    )
                    return
                payload = await response.json()
        except Exception as exc:  # noqa: BLE001 — подключение важнее модификатора
            logger.warning(f"Модификатор «{entity}» не прочитан: {exc}")
            return

        state = payload.get("state") if isinstance(payload, dict) else None
        if state in ("on", "off"):
            client.asleep = state == "on"
            # WARNING как в подписке (#70): INFO адаптера в docker-журнале не
            # виден, а прочитанное состояние — основа всех решений «спим».
            logger.warning(f"HAAdapter: «мы спим» = {client.asleep} (модификатор {entity})")

    async def get_entity_state(self, entity_id: str) -> str | None:
        """Прочитать состояние одной сущности через REST.

        Наружу, а не только для внутреннего чтения: наблюдение за батарейками
        (спека 014, FR-048) и будущая сквозная проверка здоровья дома
        (`BACKLOG.md`, F6) спрашивают состояние по имени, а не по событию.

        Args:
            entity_id: Идентификатор сущности.

        Returns:
            Состояние как строка либо ``None``, если сущность не ответила.
        """
        return await self._read_entity_state(entity_id)

    async def _read_entity_state(self, entity: str) -> str | None:
        """Прочитать состояние одной сущности через REST.

        Args:
            entity: Идентификатор сущности.

        Returns:
            Состояние как строка либо ``None``, если сущность не ответила.
        """
        client = self._ws_client
        session = self._session
        if client is None or session is None:
            return None
        base = cast(str, self._ws_url)
        base = base.replace("wss://", "https://").replace("ws://", "http://")
        url = f"{base.split('/api/websocket')[0].rstrip('/')}/api/states/{entity}"
        try:
            async with session.get(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    logger.warning(
                        f"Глобальная сущность {entity} не прочитана: "
                        f"Home Assistant ответил {response.status}"
                    )
                    return None
                payload = await response.json()
        except Exception as exc:  # noqa: BLE001 — подключение важнее значения
            logger.warning(f"Глобальная сущность {entity} не прочитана: {exc}")
            return None

        state = payload.get("state") if isinstance(payload, dict) else None
        return str(state) if state is not None else None

    async def _refresh_climate_globals(self) -> None:
        """Прочитать глобальные значения климата при подключении.

        Условия обогрева и охлаждения читают `climate_setpoint`, `is_winter` и
        остальные, но до 2026-10-10 писателя не было нигде: в бою `may_heat`
        всегда получал «данных нет», и обогрев не включался ни в одной комнате.
        Читается сразу при подключении, иначе до первого события от этих
        сущностей дом ничего не знает о цели.

        Returns:
            Ничего.
        """
        client = self._ws_client
        if client is None:
            return
        for role, entity in self.climate_entities.items():
            state = await self._read_entity_state(entity)
            client.store_global(role, state, entity)

    async def _refresh_ventilation_globals(self) -> None:
        """Прочитать глобальные значения вентиляции при подключении.

        Право владельца выключить вентиляцию и режимы проветривания и вытяжки
        живут в Home Assistant. Не прочитав их при подключении, платформа до
        первого события считала бы, что вентиляция включена, а проветривания
        нет.

        Returns:
            Ничего.
        """
        client = self._ws_client
        if client is None:
            return
        for role, entity in self.ventilation_entities.items():
            state = await self._read_entity_state(entity)
            client.store_global(role, state, entity)

    def _global_context(self) -> dict[str, Any]:
        """Прочитанные глобальные значения одним словарём.

        Returns:
            Словарь «поле клиента → значение» для контекста события.
        """
        client = self._ws_client
        if client is None:
            return {}
        fields = sorted(set(GLOBAL_ENTITY_FIELDS.values()))
        return {name: getattr(client, name, None) for name in fields}

    def _event_context(self) -> dict[str, Any]:
        """Контекст события: солнце, сон и глобальные значения.

        Returns:
            Словарь контекста без привязки к конкретному событию.
        """
        client = self._ws_client
        return {
            "daylight": getattr(client, "daylight", None),
            "sleep_modifier_on": getattr(client, "asleep", None),
            **self._global_context(),
        }

    async def _refresh_daylight(self) -> None:
        """Обновить признак «светло ли сейчас» по данным Home Assistant.

        Событие солнца приходит только на восходе и закате, поэтому после
        перезапуска платформы состояние неизвестно до следующего рассвета. Без
        этого чтения условие «темно ли» отвечал бы по времени суток, и движение
        днём не включало бы свет вообще — автоматика молчала бы до утра.

        Args:
            Ничего.

        Returns:
            Ничего. Неудача не прерывает подключение: без состояния солнца
            решение падает на время суток.
        """
        if self._ws_client is None or self._session is None:
            return
        await self._refresh_sleep_modifier()
        # Климат и вентиляция читают те же признаки, что и освещение, но иначе:
        # без уставки и сезона до первого события от этих сущностей условия
        # получают «данных нет» и решения не принимают вовсе.
        #
        # Имена сущностей передаются клиенту: он же фильтрует события подписки,
        # а этих сущностей в манифесте нет. Читать их раз в подключении мало —
        # владелец меняет уставку сам, и без реакции на событие обогрев держался
        # бы на старой цели до перезапуска (FR-001).
        client = self._ws_client
        if client is not None:
            client.climate_entities = dict(self.climate_entities)
            client.ventilation_entities = dict(self.ventilation_entities)
        await self._refresh_climate_globals()
        await self._refresh_ventilation_globals()
        # Единицы измерения таймеров обогревателей читаются здесь, а не в
        # действии: решение принимается на каждом показании датчика, и запрос в
        # сеть на каждое из них означал бы либо лишнюю нагрузку, либо отказ
        # обогрева при обрыве связи с Home Assistant.
        if self.heater_timers:
            await self.refresh_entity_units(self.heater_timers)

        http_url = cast(str, self._ws_url)
        rest_base = http_url.replace("wss://", "https://").replace("ws://", "http://")
        # Адрес сокета указывает на сам WebSocket-эндпоинт (`/api/websocket`);
        # без его отбрасывания REST-запрос уходил на несуществующий адрес и
        # отвечал 404, а состояние солнца оставалось неизвестным до заката.
        base_path = rest_base.split("/api/websocket")[0].rstrip("/")
        url = f"{base_path}/api/states/sun.sun"
        try:
            async with self._session.get(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    logger.warning(
                        f"Солнце: Home Assistant ответил {response.status} — "
                        "светлость определится по времени суток"
                    )
                    return
                payload = await response.json()
        except Exception as exc:  # noqa: BLE001 — подключение важнее освещённости
            logger.warning(f"Солнце: не удалось прочитать состояние ({exc})")
            return

        state = payload.get("state") if isinstance(payload, dict) else None
        if state in ("above_horizon", "below_horizon"):
            self._ws_client.daylight = state == "above_horizon"
            logger.info(
                "HAAdapter: освещённость получена от Home Assistant, "
                f"на улице {'светло' if self._ws_client.daylight else 'темно'}"
            )

    async def _connect_websocket(self) -> None:
        """Establish WebSocket connection with exponential backoff."""
        reconnect_delay = 1.0
        max_reconnect_delay = 60.0

        while not self._shutdown_event.is_set():
            needs_backoff = False
            try:
                log = self._get_logger(self._generate_trace_id())
                # Инструментация #70: записи цикла переподключения печатаются на
                # уровне info либо через per-connection логгер, и в этом
                # развёртывании не видны ни те, ни другие. Поэтому по журналу
                # нельзя было отличить «цикл остановился» от «цикл работает
                # молча». Уровень WARNING — единственный, который здесь виден.
                logger.warning("🔌 HAAdapter: attempting WebSocket connection (iteration)")
                logger.info(f"🔌 HAAdapter: attempting WebSocket connection to {self._ws_url}")
                log.info(f"HAAdapter: connecting to WebSocket {self._ws_url}")

                # Отладочный лог
                log.info(f"HAAdapter: HomeAssistantWS class = {HomeAssistantWS}")
                log.info(f"HAAdapter: HAS_WS_LIBRARY = {HAS_WS_LIBRARY}")

                self._session = aiohttp.ClientSession()

                # Создаём клиент
                # cast, а не проверка: __init__ уже отвергает режим websocket
                # без ws_url/token, поэтому значения здесь заведомо не None.
                # Проверка в рантайме изменила бы поведение, а сужение через
                # атрибут mypy между методами не переносит.
                self._ws_client = HomeAssistantWS(
                    url=cast(str, self._ws_url),
                    token=cast(str, self._token),
                    session=self._session,
                )
                # Живой провайдер фильтра ставится до connect()/subscribe():
                # фильтр читает манифест в момент события, а не снимок на
                # момент подписки. Раньше список замораживался, и устройство,
                # добавленное через /devices/apply, оставалось слепым до
                # рестарта (Known Issue #83). Метод — bound method, поэтому
                # провайдер всегда видит актуальное self._manifest.
                self._ws_client.entity_filter_provider = self._subscribed_entities
                # Уведомления о смене суток ставятся здесь, а не рядом с
                # чтением модификатора: декоративному свету закат нужен всегда,
                # а в доме без модификатора «мы спим» его чтение не происходит
                # вовсе — и вечернее освещение молча не включалось бы.
                self._ws_client.on_sunset = self.on_sunset
                self._ws_client.on_sunrise = self.on_sunrise

                log.info(f"HAAdapter: ws_client created = {self._ws_client}")

                # Подключаемся
                await self._ws_client.connect()

                # КРИТИЧЕСКАЯ ПРОВЕРКА: реально ли подключились?
                if not getattr(self._ws_client, "connected", False):
                    raise ConnectionError("WebSocket connect() succeeded but connected=False")

                logger.info("✅ HAAdapter: WebSocket connected successfully!")

                # Подписываемся на события.
                #
                # Фильтра на стороне Home Assistant нет: API отвергает
                # `entity_ids` в subscribe_events (проверено на живом HA
                # 2026-10-08), поэтому подписка идёт на все события, а
                # ограничение применяется у нас, в _accepts. Здесь список
                # уходит только как снимок для лога и как отправная точка
                # для лога изменений фильтра.
                #
                # Пустой список означает подписку на всё: при пустом манифесте
                # лучше получать лишнее и отбивать у себя, чем не получать
                # ничего (тогда платформа выглядит исправной и молчит).
                subscribed = self._subscribed_entities()
                filter_dict: dict[str, Any] = {"type": "state_changed"}
                if subscribed:
                    filter_dict["entity_ids"] = subscribed

                await self._ws_client.subscribe(
                    self._handle_ws_state_change,
                    filter_dict,
                )
                # INFO-запись остаётся на месте: видимость покупается добавлением
                # WARNING, а не отказом от неё. Сторож на исходном тексте
                # (tests/unit/test_ha_adapter_reconnect_loop_observable.py) требует
                # и её присутствия, и это правильно: подписка — заметное событие,
                # и INFO для неё уместен.
                log.info("HAAdapter: subscribed to state_changed events")
                # Подписка считается успешной только после ответа HA. Раньше
                # запись делалась сразу после отправки, а HA отвергал её
                # неподдерживаемым ключом `entity_ids`: журнал врал, `/ready`
                # был зелёный, события не приходили никогда.
                if not self._ws_client.subscription_confirmed:
                    reason = self._ws_client.subscription_error or "причина неизвестна"
                    logger.warning(
                        f"🔔 HAAdapter: подписка на state_changed НЕ подтверждена "
                        f"({reason}); ограничение по {len(subscribed)} сущностям "
                        f"применяется на нашей стороне"
                    )
                elif subscribed:
                    # WARNING, а не INFO: логи адаптера наследуют корневой
                    # обработчик, где info не виден — проверка на info молчала бы
                    # и не доказала бы ничего (урок #70).
                    logger.warning(
                        f"🔔 HAAdapter: subscribed to state_changed for "
                        f"{len(subscribed)} entities from manifest "
                        f"(фильтр на нашей стороне: HA его не поддерживает)"
                    )
                else:
                    logger.warning(
                        "🔔 HAAdapter: manifest lists no entities — subscribed to "
                        "ALL state_changed events"
                    )
                logger.info("🔔 HAAdapter: listening for HA state changes...")

                # Освещённость нужна сразу при подключении: событие солнца придёт
                # только на восходе или закате.
                await self._refresh_daylight()

                reconnect_delay = 1.0
                self._mark_connection_established()
                logger.info("✅ HAAdapter: WebSocket ready, backoff reset (delay=1.0s)")

                # 🆕 Инициализируем timestamp последнего события
                self._last_event_time = time.time()
                # Признак жизни соединения. Раньше порог «устаревшего» считался
                # от времени последнего события, а это время выставлялось только
                # здесь, при подключении, и нигде не обновлялось: обрыв
                # объявлялся ровно через 300 с после старта независимо от того,
                # как бурно шла жизнь дома. Тишина в доме и мёртвое соединение
                # были неразличимы.
                self._last_liveness_time = time.time()

                # 🆕 Запускаем heartbeat задачу для обнаружения мёртвых соединений
                heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                try:
                    # Ждём сигнала остановки или завершения listen_task
                    listen_task = getattr(self._ws_client, "_listen_task", None)
                    if listen_task is not None and not listen_task.done():
                        tasks = [
                            asyncio.ensure_future(self._shutdown_event.wait()),
                            listen_task,
                        ]

                        done, pending = await asyncio.wait(
                            tasks,
                            return_when=asyncio.FIRST_COMPLETED,
                        )

                        reason = "listen task ended"
                        if listen_task in done:
                            reason = self._listen_task_reason(listen_task, log)
                    else:
                        # Задача чтения отсутствует или уже завершилась. Ждать
                        # дальше нечего: в ожидании остался бы только флаг
                        # остановки, который сам никогда не сработает. Прежний
                        # код именно так и уходил в ожидание forever — платформа
                        # навсегда переставала получать события, ни разу не
                        # написав об обрыве (Known Issue #70).
                        reason = "listen task missing or already done"

                    self._record_disconnect(reason, reconnect_delay)
                    needs_backoff = True
                finally:
                    # Останавливаем heartbeat при любом выходе
                    heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat_task

            except asyncio.CancelledError:
                # Ветка видна: она выходит из цикла, не делая ни паузы, ни
                # повторного подключения, и без записи выглядит как зависание.
                # Уровень WARNING — logger.info здесь не виден (#70).
                logger.warning("HAAdapter: reconnect loop cancelled - no retry will happen")
                break

            except Exception as e:
                trace_id = self._generate_trace_id()
                log = self._get_logger(trace_id)
                logger.error(f"❌ HAAdapter connection failed: {type(e).__name__}: {e}")
                if not isinstance(e, (ConnectionError, OSError, TimeoutError)):
                    logger.exception("HAAdapter: unexpected connection error")
                log.error(f"HAAdapter: connection error: {type(e).__name__}: {e}")

                # Логируем состояние для отладки
                log.error(f"HAAdapter: _ws_client is None = {self._ws_client is None}")
                if self._ws_client is not None:
                    log.error(
                        f"HAAdapter: _ws_client.connected = {getattr(self._ws_client, 'connected', 'N/A')}"
                    )
                    log.error(f"HAAdapter: _ws_client.ws = {getattr(self._ws_client, 'ws', 'N/A')}")

                self._record_disconnect(f"{type(e).__name__}: {e}", reconnect_delay)
                needs_backoff = True

            finally:
                await self._cleanup_websocket()

            if needs_backoff and not self._shutdown_event.is_set():
                logger.warning(f"🔄 HAAdapter: retrying in {reconnect_delay:.1f}s (visible)")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
            elif needs_backoff:
                # Ветка «нужна пауза, но система останавливается» раньше уходила
                # молча: цикл выходил из while по установленному _shutdown_event,
                # и в журнале не оставалось ни единой записи. Теперь видно.
                logger.warning("HAAdapter: backoff skipped, shutdown_event is set")

        logger.warning("HAAdapter: reconnect loop exited")

    @staticmethod
    def _listen_task_reason(listen_task: asyncio.Task[Any], log: Any) -> str:
        """Классифицирует завершение задачи чтения.

        Отдельный метод, а не три строки в цикле, потому что именно тут
        исходное исключение важно различать, а различение легко потерять:
        `CancelledError` не наследует `Exception`, поэтому `listen_task.result()`
        на отменённой задаче уходил в обработчик отмены самого цикла, цикл
        выходил, и переподключения не происходило никогда (#70).

        Отмена задачи чтения — ожидаемый исход при закрытии устаревшего
        соединения: так её останавливает heartbeat. Это обрыв, а не остановка
        платформы.

        Args:
            listen_task: Задача чтения.
            log: Журнал соединения.

        Returns:
            Причина завершения для `_record_disconnect`.
        """
        if listen_task.cancelled():
            return "listen task cancelled"
        try:
            listen_task.result()
        except Exception as error:
            log.warning(f"HAAdapter: listen_task ended unexpectedly: {error}")
            return f"listen task failed: {error}"
        return "listen task ended"

    async def _handle_ws_state_change(
        self,
        message: dict[str, Any],
        trace_id: str | None = None,
    ) -> None:
        trace_id = trace_id or self._generate_trace_id()
        log = self._get_logger(trace_id)
        self._last_liveness_time = time.time()

        try:
            entity_id = message.get("entity_id", "")
            old_state_obj = message.get("old_state", {})
            new_state_obj = message.get("new_state", {})

            old_state = old_state_obj.get("state", "unknown") if old_state_obj else "unknown"
            new_state = new_state_obj.get("state", "unknown") if new_state_obj else "unknown"

            logger.info(f"📡 HA STATE CHANGE: {entity_id}: '{old_state}' -> '{new_state}'")
            log.info(
                f"HAAdapter: WebSocket state_change for {entity_id}: '{old_state}' -> '{new_state}'"
            )

            # Указание пользователя лежит в конверте события, а не в его данных.
            # Раньше оно подставлялось заглушкой и терялось: без него платформа
            # не отличала «человек выключил свет» от «сработал сценарий», а
            # ручная блокировка не включалась ни одним путём. Именно поэтому
            # человек гасил свет, а автоматика включала его обратно.
            ha_context = message.get("context") or {}

            await self.on_state_change(
                entity_id=entity_id,
                new_state=new_state,
                old_state=old_state,
                context={
                    "trace_id": trace_id,
                    "source": "websocket",
                    "user_id": ha_context.get("user_id"),
                    "ha_context_id": ha_context.get("id"),
                    "daylight": getattr(self._ws_client, "daylight", None),
                    # «Мы спим» приходит из Home Assistant: сущность есть, но её
                    # состояние платформе неизвестно — тогда решает неё, а не
                    # часы платформы (см. условие may_turn_on).
                    "sleep_modifier_on": getattr(self._ws_client, "asleep", None),
                    # Глобальные значения климата и вентиляции. Неизвестное
                    # едет как None: условие читает его как «решать не на чём»,
                    # а не как «не зима» и не как «в комнате ноль градусов».
                    **self._global_context(),
                },
            )

        except Exception as e:
            log.error(f"HAAdapter: error handling WebSocket state change: {e}")

    async def _cleanup_websocket(self) -> None:
        if self._ws_client is not None:
            with contextlib.suppress(Exception):
                await self._ws_client.close()
            self._ws_client = None

        if self._session is not None:
            with contextlib.suppress(Exception):
                await self._session.close()
            self._session = None

    def _subscribed_entities(self) -> list[str]:
        """Сущности из манифеста, на которые подписан адаптер.

        Берутся из манифеста через тот же механизм, что и в `EventRouter`, чтобы
        источник истины был один: подписка и маршрутизация не должны
        расходиться, иначе платформа будет получать события, которые не
        маршрутизирует, либо не получать те, которые маршрутизирует.

        Returns:
            Список `entity_id`; пустой, если манифест недоступен или пуст.
        """
        manifest = getattr(self, "_manifest", None)
        if manifest is None:
            return []

        from core.events.event_router import collect_subscribed_entities

        return collect_subscribed_entities(manifest)

    async def _force_disconnect(self, reason: str) -> None:
        """Объявить соединение мёртвым и освободить сокет.

        Закрытие здесь — не гигиена, а условие переподключения. Цикл в
        `_connect_websocket` ждёт завершения задачи чтения, и при разрыве без
        чистого закрытия (отвал Wi-Fi, `docker network disconnect`) эта задача
        не завершается никогда: `recv()` ждёт данных, которых не будет. Пока сокет
        открыт и помечен лишь флагом, цикл остаётся в `asyncio.wait(...)`, а
        heartbeat со следующей итерации выходит по `if not connected: continue` —
        то есть выключает себя сам. Обрыв был обнаружен и записан, а
        переподключения не происходило никогда (#78).

        Args:
            reason: Причина обрыва — попадает в журнал.
        """
        client = self._ws_client
        if client is None:
            return

        client.connected = False
        try:
            await client.close()
        except Exception as error:  # noqa: BLE001 — обрыв не должен ронять heartbeat
            # Закрытие может не завершиться на мёртвом сокете; обрыв всё равно
            # объявлен, и следующая попытка подключения его разберёт.
            logger.warning(f"HAAdapter: close after '{reason}' failed: {error}")

    async def _heartbeat_loop(self) -> None:
        """Проверять живость соединения и переподключать мёртвое.

        Задача — находить мёртвые соединения, а не шумные дома. Поэтому порядок
        шагов важен: **сначала признак жизни, потом вывод**. Если сначала судить
        по тишине, а потом спрашивать сокет, то вывод всегда опережает проверку:
        при очередном пробуждении тишина уже «пять минут», и исправное соединение
        рвётся, не успев ни разу ответить на ping.

        Признак жизни обновляется тремя способами: при подключении, на каждом
        входящем событии и на каждом успешном ответе на ping. Ответ на ping —
        прямое доказательство, что соединение в порядке, даже если событий не
        было вовсе.

        Неотвечающий сокет приводит к обрыву, и обрыв обязан быть настоящим:
        соединение закрывается, а не только помечается флагом — иначе цикл
        переподключения не заметит обрыва никогда (#78).
        """
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(30)  # Check every 30 seconds

                if not (self._ws_client and getattr(self._ws_client, "connected", False)):
                    continue

                # Шаг 1: спросить у сокета, жив ли он.
                try:
                    ws = getattr(self._ws_client, "ws", None)
                    if ws and hasattr(ws, "ping"):
                        await asyncio.wait_for(ws.ping(), timeout=5)
                        # Ответ пришёл — соединение живо, даже если событий не было.
                        self._last_liveness_time = time.time()
                        logger.debug("HAAdapter: WebSocket ping sent")
                except Exception as e:
                    # Запись до закрытия: если `close()` не вернётся на мёртвом
                    # сокете, по журналу должно быть видно, что обрыв найден.
                    logger.warning(f"HAAdapter: ping failed ({e}), forcing reconnect")
                    await self._force_disconnect(f"ping failed: {e}")
                    return

                # Шаг 2: судить по признаку жизни, а не по тишине.
                last_liveness = getattr(self, "_last_liveness_time", None)
                if last_liveness is None:
                    last_liveness = getattr(self, "_last_event_time", None)
                if last_liveness is None:
                    continue
                time_since = time.time() - last_liveness
                if time_since > 300:  # 5 minutes without any sign of life
                    logger.warning(
                        f"HAAdapter: No sign of life for {time_since:.0f}s "
                        f"(no events, no ping reply), connection is stale - forcing reconnect"
                    )
                    logger.warning("HAAdapter: closing stale connection")
                    await self._force_disconnect("stale connection")
                    logger.warning("HAAdapter: stale connection closed, heartbeat will resume")
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        # ВИДИМО: единственное место в коде, где отменяется задача цикла
        # переподключения (#70). Пока запись шла на info, было невозможно отличить
        # «отменил stop()» от «отмена пришла изнутри» — обе выглядели одинаково.
        logger.warning(
            f"HAAdapter: stop() called, cancelling reconnect task (task={self._reconnect_task!r})"
        )
        logger.info("HAAdapter: initiating graceful shutdown")
        self._shutdown_event.set()

        if self._reconnect_task is not None and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None

        if self._mode == "websocket":
            await self._cleanup_websocket()

        logger.info("HAAdapter: shutdown complete")

    def register_trace_callback(
        self,
        callback: Callable[[str, str, str, dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        self._trace_callbacks.append(callback)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_connected(self) -> bool:
        """Есть ли живое соединение с Home Assistant.

        Returns:
            True, если соединение действительно есть.
        """
        if self._mode == "pyscript":
            return True
        return self._ws_client is not None and self._ws_client.connected

    @property
    def last_disconnect_reason(self) -> str | None:
        """Причина последнего разрыва соединения.

        Отдаётся наружу для `/ready`: оператор должен видеть не только факт
        отсутствия связи, но и то, кто её разорвал.

        Причина хранится на адаптере, а не на клиенте: cleanup обнуляет
        ``_ws_client``, а каждая попытка восстановления создаёт нового
        клиента — на клиенте она не доживала бы до наблюдателя (B29,
        живой обрыв 2026-10-08). Клиент остаётся запасным источником:
        адаптер, собранный без ``__init__`` (тесты), и свежий клиент,
        у которого причина ещё не записана, работают как раньше.

        Returns:
            Причина разрыва или ``None``, если разрывов не было.
        """
        stored = getattr(self, "_last_disconnect_reason", None)
        if stored is not None:
            return stored
        if self._ws_client is None:
            return None
        return getattr(self._ws_client, "_disconnect_reason", None)


HomeAssistantAdapter = HAAdapter
