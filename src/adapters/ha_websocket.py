"""Транспорт WebSocket для Home Assistant (BACKLOG B80).

Вынесен из `ha_adapter.py`: это отдельная ответственность — соединение, подписка
на события и команды, — и она занимала почти треть файла. Адаптер поверх него
занимается домом: устройствами, контекстом, зеркалом.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol, runtime_checkable

from adapters.ha_constants import (
    _BOOLEAN_ROLES as _BOOLEAN_ROLES,
    _NUMERIC_ROLES as _NUMERIC_ROLES,
    GLOBAL_ENTITY_FIELDS as GLOBAL_ENTITY_FIELDS,
    MANUAL_OFF_VALUES as MANUAL_OFF_VALUES,
    MANUAL_ON_VALUES as MANUAL_ON_VALUES,
    OWN_CONTEXT_KEEP as OWN_CONTEXT_KEEP,
    SUBSCRIPTION_TIMEOUT_SEC as SUBSCRIPTION_TIMEOUT_SEC,
    WS_CLOSE_TIMEOUT_SEC as WS_CLOSE_TIMEOUT_SEC,
)
from adapters.ha_ws_connection import HaWsConnectionMixin
from adapters.ha_ws_events import HaWsEventsMixin
from adapters.ha_ws_filters import HaWsFiltersMixin
from adapters.ha_ws_values import _as_float as _as_float, _is_number as _is_number


logger = logging.getLogger(__name__)


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


class SimpleHAWebSocketClient(
    HaWsFiltersMixin,
    HaWsEventsMixin,
    HaWsConnectionMixin,
):
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
        # Глобальные сущности света: день/ночь и текущая цветовая температура.
        # Их нет в манифесте, но действия включения читают текущее значение, а
        # служба света пишет его в Home Assistant.
        self.lighting_entities: dict[str, str] = {}
        # Флаги штор (спека 015): «кто-то дома», «дома собаки», разрешение
        # закрывать ночью и аварийный флаг. Шторы зависят только от них.
        self.cover_entities: dict[str, str] = {}
        # Куда класть прочитанное значение: роль → поле этого же клиента.
        self.global_fields: dict[str, str] = dict(GLOBAL_ENTITY_FIELDS)
        # Уведомление платформы о включении «мы спим»: модификатор гасит свет,
        # но событие устройства это не событие устройства — сущность не входит
        # в подписку и фильтр её всегда отбрасывает. Поэтому переключение
        # ловится здесь, в разборе, и доносится отдельным путём в _deliver.
        self.on_sleep_started: Callable[[], Awaitable[None]] | None = None
        # Запрошено ли уведомление; флаг живёт одно событие.
        self._pending_sleep_started = False
        # Смена модификатора «мы спим» в любую сторону. Свету хватает одного
        # ``sleep_started`` (гасить), но шторы и вентиляция решают по смене флагов
        # дома, а сущности модификатора нет в подписке — без отдельного
        # уведомления они о ней не узнают (боевой случай 2026-10-16: «мы спим»
        # включился в полночь, шторы остались открытыми до утра).
        self.on_sleep_changed: Callable[[], Awaitable[None]] | None = None
        self._pending_sleep_changed = False
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
        # Разрешение автоматике включать плановый свет (основное уличное
        # освещение) по закату. None — сущность не прочитана; это не «не
        # разрешено», поэтому до первого чтения автоматика не решает.
        self.scheduled_light_enabled: bool | None = None
        # Размер фильтра при последнем наблюдении. Нужен, чтобы изменение
        # состава подписки было видно в журнале, а не только в памяти кода.
        self._filter_size_last_seen: int = 0

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

    async def command(self, command_type: str, **payload: Any) -> dict[str, Any]:
        """Отправить команду Home Assistant и дождаться ответа.

        Нужна для того, что не покрыто ``get_states`` и ``call_service``: реестр
        сущностей и панели (BACKLOG B77). Без них чистка мусора была бы гаданием:
        «выведен на панель» и «описан в YAML» — разные вещи.

        Args:
            command_type: Тип команды WebSocket Home Assistant.
            **payload: Дополнительные поля команды.

        Returns:
            Ответ дома целиком: ``success`` и ``result`` либо ``error``. Ошибку
            разбирает вызывающий: молчаливый ``None`` не отличить от «пусто».
        """
        if not self.ws or not self.connected:
            return {
                "success": False,
                "error": {"code": "not_connected", "message": "нет связи с домом"},
            }

        self._msg_id += 1
        msg_id = self._msg_id

        await self.ws.send(json.dumps({"id": msg_id, "type": command_type, **payload}))

        try:
            return await asyncio.wait_for(self._request_result(msg_id), timeout=15)
        except TimeoutError:
            return {
                "success": False,
                "error": {"code": "timeout", "message": "дом не ответил вовремя"},
            }

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
            except TimeoutError:
                return None
            # Home Assistant отвечает `success: false` на отказ сервиса (например,
            # лишний ключ в данных команды). Без этой проверки отказ выглядел как
            # успех: адаптер печатал «выполнен», и цепочка «решение → команда →
            # прибор» считалась исправной, хотя команду отбило (боевой разбор
            # 2026-10-12: `fan.set_preset_mode` с лишним полем).
            if isinstance(response, dict) and response.get("success") is False:
                raise RuntimeError(
                    f"HA service {domain}.{service} failed: {response.get('error')!r}"
                )
            return response.get("result")
        else:
            await self.ws.send(json.dumps(payload))
            return None


HAS_WS_LIBRARY = True

SETPOINT_EPSILON = 0.05
