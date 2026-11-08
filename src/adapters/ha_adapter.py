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
import logging
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, Any, cast

import aiohttp

from adapters.ha_constants import (
    _BOOLEAN_ROLES as _BOOLEAN_ROLES,
    _COVER_RETRIGGER_ROLES as _COVER_RETRIGGER_ROLES,
    _LIGHTING_RETRIGGER_ROLES as _LIGHTING_RETRIGGER_ROLES,
    _NUMERIC_ROLES as _NUMERIC_ROLES,
    _VENTILATION_RETRIGGER_ROLES as _VENTILATION_RETRIGGER_ROLES,
    COMMAND_ECHO_WINDOW_SEC as COMMAND_ECHO_WINDOW_SEC,
    DIVERGENCE_COMMAND_WINDOW_SEC as DIVERGENCE_COMMAND_WINDOW_SEC,
    GLOBAL_ENTITY_FIELDS as GLOBAL_ENTITY_FIELDS,
    MANUAL_OFF_VALUES as MANUAL_OFF_VALUES,
    MANUAL_ON_VALUES as MANUAL_ON_VALUES,
    OWN_CONTEXT_KEEP as OWN_CONTEXT_KEEP,
    SUBSCRIPTION_TIMEOUT_SEC as SUBSCRIPTION_TIMEOUT_SEC,
    WS_CLOSE_TIMEOUT_SEC as WS_CLOSE_TIMEOUT_SEC,
)
from adapters.ha_websocket import (
    HAS_WS_LIBRARY as HAS_WS_LIBRARY,
    SETPOINT_EPSILON as SETPOINT_EPSILON,
    ActionGateProtocol as ActionGateProtocol,
    AlwaysExecuteGate as AlwaysExecuteGate,
    SimpleHAWebSocketClient as SimpleHAWebSocketClient,
    _as_float as _as_float,
    _is_number as _is_number,
)
from adapters.home_assistant import dashboards as dashboards_api
from adapters.home_assistant.commands import CommandGatewayMixin
from adapters.home_assistant.connection import ConnectionMixin
from adapters.home_assistant.discovery import DiscoveryMixin
from adapters.home_assistant.manual_events import ManualEventsMixin
from adapters.home_assistant.units import UnitsMixin


# Use standard logging instead of loguru for consistency with logging_service
logger = logging.getLogger(__name__)

#: Значения, означающие «включено» при ручном изменении: по ним автомату уходит
#: ``manual_switch_on`` (BACKLOG B57).

#: Значения, означающие «выключено»: автомату уходит ``manual_switch_off``.


# Предел ожидания закрытия WebSocket. Закрытие идёт по рукопожатию, и на
# молчащем соединении оно может не прийти вовсе; ждать бесконечно означает
# остановить heartbeat и основной цикл адаптера (#70).

#: Сколько ждём ответа HA на подписку.
#:
#: Отдельно от закрытия: подписка не закрывает соединение, но без ответа на неё
#: события не придут, а узнать об этом можно только по отсутствию событий.
#: Константа, а не число в коде, чтобы проверки не ждали десять секунд каждая.

#: Сколько последних контекстов своих команд помнит адаптер.
#:
#: Идентификаторов ровно столько, сколько команд платформа отправила за
#: последние минуты: у каждой свой, и хранить их вечно незачем. Восемь
#: устройств при переходах каждые несколько секунд дают порядка сотни записей,
#: поэтому 256 — с запасом и без роста памяти.

#: Сколько секунд после своей команды изменение устройства считать своим.
#:
#: `context.id` работает не для всех интеграций: боевой рекуператор Vakio
#: обновляет состояние так, что контекст команды до адаптера не доходит, и
#: платформа записывала собственную команду ручным действием — после каждого
#: своего решения включалась 60-минутная блокировка против себя, и рекуператор
#: оставался на прежнем режиме (в бою 2026-10-13: жарко в комнате, а прибор на
#: ночном минимуме 14 %). Временное окно закрывает эту дыру: если мы только что
#: командовали этому устройству, его изменение — наше.


# Always use SimpleHAWebSocketClient (no external dependency)
# Псевдоним класса для читаемости аннотаций; присваивание само по себе
# корректно, поэтому подавлять здесь нечего (прежний ``# type: ignore`` был
# лишним — mypy сообщал unused-ignore).
HomeAssistantWS = SimpleHAWebSocketClient


if TYPE_CHECKING:
    from core.commands.middleware import ManualLockoutMiddleware
    from core.events.event_router import EventRouter


#: Погрешность сравнения уставки. Шаг слайдера — 0.5 °C, поэтому меньшие
#: расхождения — плавание дробных значений, а не разное мнение источников.


#: Роли глобальных сущностей климата и вентиляции и поле клиента, которое они
#: заполняют. Ключ роли совпадает с ключом в правилах дома
#: (``automation_rules.climate`` / ``.ventilation``), значение — с полем, которое
#: читает условие.
#:
#: Отдельная таблица, а не разбор имени: читаемость важнее экономии строки, а
#: при несовпадении имён тест укажет на конкретное место.

#: Сущности, значение которых — булево: ``on``/``off`` из Home Assistant.

#: Сущности, значение которых — число: ``number.*`` и ``sensor.*`` температуры.

#: Роли глобальных сущностей, смена которых обязана немедленно пересмотреть
#: автоматы вентиляции. Эти значения живут в Home Assistant и приходят не от
#: датчика: выключатель владельца, фиче-флаг дома, сезон и модификаторы
#: проветривания/вытяжки. Автомат вентиляции ждёт показания температуры, поэтому
#: без этого переключатель владельца не действовал, пока датчик молчал: в бою
#: 2026-10-12 рекуператор продолжал дуть сырым притоком на 91 %, хотя владелец
#: выключил вентиляцию, — события датчика не было больше часа.
#:
#: Порог «жарко» (``comfort_max``) и уставка комнаты (``setpoint``) — тоже
#: переключатели, только числовые: правила FR-049/FR-051 (вентиляция стоит ниже
#: уставки, «Приток MAX» выше потолка комфорта) опираются на них, и смена порога
#: владельцем обязана пересмотреть решение сразу, а не на следующем показании
#: датчика, которого может не быть часами (B42).

#: Роли глобальных сущностей, смена которых обязана немедленно пересмотреть
#: автоматы штор (спека 015). Шторы не слушают датчик вообще: их решение зависит
#: только от флагов дома, поэтому без немедленного пересмотра штора не сдвинулась
#: бы до смены флага, которого может не быть часами. Модификатор «мы спим» сюда не
#: входит отдельно: его смена отлавливается по имени сущности (``sleep_modifier_entity``).


#: Причины чтения одной сущности по имени (аудит 2026-10-16, К-5).
#:
#: Разделены намеренно: «сущности нет в доме» — дело оператора (опечатка в
#: манифесте или снятый прибор), «не прочитали» — временная беда, которая
#: лечится повтором. Прежде оба случая давали `None`, и опечатка в манифесте
#: выглядела как обрыв связи: обогрев не включался, а причина называлась одна.
READ_OK = "ok"
READ_ENTITY_ABSENT = "entity_absent"
READ_FAILED = "read_failed"
READ_NO_CONNECTION = "no_connection"


class HAAdapter(
    UnitsMixin, ManualEventsMixin, DiscoveryMixin, CommandGatewayMixin, ConnectionMixin
):
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
        #: Пользователь, которому принадлежит токен платформы (B92). Узнаётся из
        #: возврата собственной команды: её контекст помечен нашим `context.id`, а
        #: `user_id` — тот, кому принадлежит токен. Отдельного запроса не нужно.
        self._own_user_id: str | None = None
        self._event_router = event_router
        # Сущность Home Assistant «мы спим»; задаётся правилами освещения в
        # манифесте. Значение читает служба суточного цикла при старте.
        self.sleep_modifier_entity: str | None = None
        # Сущности глобальных значений климата и вентиляции: роль → entity_id.
        # Задаются контейнером из правил дома и читаются при подключении, иначе
        # до первого события платформа не знает ни уставки, ни сезона.
        self.climate_entities: dict[str, str] = {}
        self.ventilation_entities: dict[str, str] = {}
        self.lighting_entities: dict[str, str] = {}
        self.cover_entities: dict[str, str] = {}
        # Был ли уже первый пересмотр настроек после запуска платформы. Первый
        # помечается одноразовым признаком ``_startup_reapply``: восстановленному автомату
        # нужен вход прибора, а не только режим (B43). При переподключении
        # признак не ставится — прибор уже работает, и лишнее включение с
        # процентом сбрасывало бы его режим (боевой разбор 2026-10-13).
        self._startup_reapply_done = False
        # Сущности, об отсутствии которых уже сказано в журнале. Дом отвечает
        # 404 не переставая, поэтому одна опечатка в манифесте писалась бы при
        # каждом чтении и каждом подключении; жалоба нужна одна (К-5).
        self._absent_reported: set[str] = set()
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
        # Уведомление о включении лампы человеком: служба температуры сразу
        # применяет актуальный оттенок, не дожидаясь пятиминутного цикла и не
        # упираясь в ручную блокировку (требование владельца 2026-10-24).
        self.on_light_turned_on: Callable[[str], Awaitable[None]] | None = None
        # Контексты команд, которые отправила сама платформа. Home Assistant
        # возвращает `context.id` на каждый вызов сервиса, и изменение состояния
        # несёт тот же идентификатор: по нему собственная команда отличается от
        # действия человека. Без этого первая же автоматическая команда
        # возвращалась в адаптер как ручное действие (HA ставит `user_id`
        # владельца токена) и включала блокировку против самой себя на 60 минут
        # — вскрыто первым живым запуском 2026-10-08.
        self._own_context_ids: deque[str] = deque(maxlen=OWN_CONTEXT_KEEP)
        # Устройства, которым платформа только что отправляла команду: время
        # (monotonic) последней команды. Нужны там, где `context.id` от
        # интеграции не доходит (см. COMMAND_ECHO_WINDOW_SEC).
        self._recent_commands: dict[str, float] = {}
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
        # Обогреватель -> его таймер: нужно, чтобы приложить к событию
        # единицу измерения именно его таймера.
        self.heater_timer_of: dict[str, str] = {}
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

    async def get_state(self, entity_id: str) -> str | None:
        """Текущее состояние прибора из Home Assistant.

        Нужно шагам команды с порядком: обогреватель принимает таймер только
        уже включённым, а таймер на выключенном приборе Home Assistant пишет
        без ошибки — то есть отказ неотличим от успеха.

        Args:
            entity_id: Сущность Home Assistant.

        Returns:
            Состояние прибора либо ``None``, если прочитать не удалось. ``None``
            трактуется как «не выполнено»: пропуск шага безопаснее отправки
            команды вслепую.
        """
        if self._session is None or not self._token:
            return None

        http_url = cast(str, self._ws_url)
        base = http_url.replace("wss://", "https://").replace("ws://", "http://")
        base = base.split("/api/websocket")[0].rstrip("/")
        try:
            async with self._session.get(
                f"{base}/api/states/{entity_id}",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    logger.warning(
                        f"HAAdapter: состояние {entity_id} не прочитано (HTTP {response.status})"
                    )
                    return None
                payload = await response.json()
        except (TimeoutError, aiohttp.ClientError, ValueError) as error:
            logger.warning(f"HAAdapter: состояние {entity_id} не прочитано: {error}")
            return None

        state = payload.get("state")
        return state if isinstance(state, str) else None

    async def get_attribute(self, entity_id: str, attribute: str) -> Any:
        """Прочитать атрибут сущности Home Assistant.

        Цель климат-устройства (`climate.*`) живёт в атрибуте `temperature`,
        а не в состоянии: состояние климата — это режим (heat/off). Уставка
        дома — цель термостата, поэтому без чтения атрибута синхронизация
        «термостат ↔ уставка» нечем сверить (требование владельца
        2026-10-12).

        Args:
            entity_id: Сущность Home Assistant.
            attribute: Имя атрибута.

        Returns:
            Значение атрибута либо ``None``, если не прочитать.
        """
        if self._session is None or not self._token:
            return None

        http_url = cast(str, self._ws_url)
        base = http_url.replace("wss://", "https://").replace("ws://", "http://")
        base = base.split("/api/websocket")[0].rstrip("/")
        try:
            async with self._session.get(
                f"{base}/api/states/{entity_id}",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    return None
                payload = await response.json()
        except (TimeoutError, aiohttp.ClientError, ValueError):
            return None

        if not isinstance(payload, dict):
            return None
        attributes = payload.get("attributes")
        return attributes.get(attribute) if isinstance(attributes, dict) else None

    async def get_automation_configs(self) -> dict[str, Any]:
        """Прочитать правила автоматизаций Home Assistant.

        Списком этот API автоматизации не отдаёт (``config/automation/list``
        отвечает ``unknown_command``), но каждую конфигурацию видно по
        идентификатору из состояния автоматизации. Без неё чистка мусора
        (BACKLOG B77) не отличает «никому не нужен» от «нужен чужому правилу», а
        цена такой ошибки — тихо сломавшаяся автоматизация.

        Returns:
            Словарь ``{идентификатор: правило}``; пусто, если прочитать не удалось
            или автоматизаций в доме нет.
        """
        session = self._session
        if session is None or not self._token:
            return {}

        states = await self.get_all_states()
        config_ids = sorted(
            {
                str(item["attributes"]["id"])
                for item in states
                if isinstance(item, dict)
                and str(item.get("entity_id", "")).startswith("automation.")
                and isinstance(item.get("attributes"), dict)
                and item["attributes"].get("id")
            }
        )
        if not config_ids:
            return {}

        http_url = cast(str, self._ws_url)
        base = http_url.replace("wss://", "https://").replace("ws://", "http://")
        base = base.split("/api/websocket")[0].rstrip("/")
        headers = {"Authorization": f"Bearer {self._token}"}
        gate = asyncio.Semaphore(8)

        async def read_one(config_id: str) -> tuple[str, Any]:
            async with gate:
                try:
                    async with session.get(
                        f"{base}/api/config/automation/config/{config_id}",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as response:
                        if response.status != 200:
                            return config_id, None
                        return config_id, await response.json()
                except (TimeoutError, aiohttp.ClientError, ValueError) as error:
                    logger.warning(f"HAAdapter: автоматизация {config_id} не прочитана: {error}")
                    return config_id, None

        pairs = await asyncio.gather(*(read_one(config_id) for config_id in config_ids))
        return {config_id: config for config_id, config in pairs if config is not None}

    async def on_state_change(
        self,
        entity_id: str,
        new_state: str,
        old_state: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Обработать изменение состояния из Home Assistant.

        Args:
            entity_id: Сущность.
            new_state: Новое состояние.
            old_state: Прежнее состояние.
            context: Контекст события.
        """
        context = context or {}

        user_id = context.get("user_id")
        # Кнопки и автоматизации владельца — его интерфейс (решение владельца
        # 2026-10-19: «кнопки это только интерфейс, управлять должна платформа»).
        # Нажатие физической кнопки в этом доме вызывает автоматизацию Home
        # Assistant, а не команду платформы, поэтому в контексте изменения есть
        # `parent_id` (автоматизация) и нет `user_id`. Без этой ветки платформа
        # не видела в нажатии человека: свет, включённый кнопкой, оставался
        # гореть, потому что модель продолжала считать его выключенным, а
        # модификатор «мы спим» и истечение оверрайда ни на что не влияли.
        #
        # Действия приборов без контекста (настенный выключатель) для света
        # считаются ручными (B89); у остальных доменов остаётся наблюдение B91.
        automation_id = context.get("ha_parent_id")
        # Собственная команда платформы возвращается из Home Assistant с тем же
        # `user_id`, что и действия из приложения, и без этой проверки
        # засчитывалась бы ручным действием: первая же автоматическая команда
        # включала блокировку против самой себя (живой запуск 2026-10-08).
        own_context = self._is_own_context(context.get("ha_context_id"))
        own_user_id = getattr(self, "_own_user_id", None)
        if own_context and user_id and own_user_id is None:
            # Свой пользователь узнаётся из возврата собственной команды: контекст
            # помечен нашим `context.id`, а `user_id` — тот, кому принадлежит
            # токен (B92). Первый же обмен даёт точное правило без лишнего запроса.
            self._own_user_id = str(user_id)
            logger.warning(f"HAAdapter: свои команды идут от пользователя {self._own_user_id}")
            own_user_id = self._own_user_id
        own_action = own_context or self._is_recent_command(entity_id)
        # B92: у платформы свой пользователь (B45), поэтому чужой `user_id` —
        # доказательство человека, даже если его действие пришло в 20-секундном
        # окне после нашей команды. Прежде такое действие считалось эхом, и
        # сторож мог повторить своё решение против человека. Своего пользователя
        # ещё не знаем — остаётся прежнее правило, иначе первая же команда
        # включала бы блокировку против себя.
        if own_user_id is None:
            human_user = bool(user_id) and not own_action
        else:
            human_user = bool(user_id) and str(user_id) != own_user_id
        human_action = human_user or (bool(automation_id) and not own_action)
        # Физический пульт шторы не оставляет `user_id` и `parent_id`: для
        # платформы это «прибор сам поехал». Но движение (`opening`/`closing`)
        # — достаточное доказательство человека, а не наша команда: свои
        # команды отсекаются `own_action`. Без этого ручное движение шторы не
        # включало локкаут, и следующая смена флагов дома отменяла выбор
        # человека (B104).
        cover_movement = (
            entity_id.startswith("cover.")
            and new_state in ("opening", "closing")
            and not own_action
            and not human_action
        )
        # Физическое/настенное действие без родителя и нашей команды —
        # доказательство человека. Для света это выключатель (B89), для климата
        # — выключение розетки обогревателя (живая находка 2026-11-08).
        # Классификация и запись блокировки живут в ManualEventsMixin.
        physical_manual = self._note_physical_manual(
            entity_id,
            new_state,
            user_id,
            automation_id,
            context,
            own_action,
            human_action,
        )
        if human_action and self._manual_lockout_middleware:
            # Диагностика, а не догадка: если команда платформы всё-таки
            # засчиталась ручным действием, утренний разбор должен видеть, почему
            # (чей пользователь или какая автоматизация, какой контекст,
            # командовали ли мы этому прибору и когда). Боевой случай 2026-10-14:
            # группа ночного освещения получила «ручное действие» в 17:37:51,
            # хотя в ту же секунду выключались её лампы нашей командой.
            logger.warning(
                f"HAAdapter: ручное действие — {entity_id}, user={user_id or '-'}, "
                f"автоматизация={automation_id or '-'}, "
                f"context={context.get('ha_context_id')}, "
                f"своя команда этому прибору: "
                f"{'была' if self._is_recent_command(entity_id) else 'не найдена'}"
            )
            self._manual_lockout_middleware.record_manual_control(entity_id)
        elif cover_movement and self._manual_lockout_middleware:
            logger.warning(
                f"HAAdapter: ручное движение шторы — {entity_id}, "
                f"user={user_id or '-'}, автоматизация={automation_id or '-'}, "
                f"context={context.get('ha_context_id')}, "
                f"своя команда этому прибору: "
                f"{'была' if self._is_recent_command(entity_id) else 'не найдена'}"
            )
            self._manual_lockout_middleware.record_manual_control(entity_id)
        elif own_action and not human_user:
            logger.debug(
                f"HAAdapter: изменение {entity_id} вызвано командой платформы, "
                f"ручным действием не считается"
            )

        trace_id = context.get("trace_id") or self._generate_trace_id()
        log = self._get_logger(trace_id)

        log.info(
            f"HAAdapter: state_change received for {entity_id}: '{old_state}' -> '{new_state}'"
        )

        client = self._ws_client
        role_of = getattr(client, "global_role", None)
        setpoint_role = role_of(entity_id) if role_of is not None else None
        if setpoint_role in ("setpoint", "thermostat"):
            # Синхронизация «термостат ↔ уставка» (требование владельца
            # 2026-10-12): источник истины — последнее изменённое, вторая
            # сторона зеркалится. Наша собственная команда сюда не попадает
            # (own_action) — иначе термостат и уставка ввалились бы в петлю.
            with contextlib.suppress(Exception):
                await self.sync_setpoint(entity_id, new_state, own_action)

        event_context: dict[str, Any] = {
            **self._event_context(entity_id),
            **context,
            "trace_id": trace_id,
        }
        if setpoint_role is not None:
            # Какая именно глобальная сущность изменилась. Шаблоны,
            # реагирующие на смену настроек, должны отличать «владелец
            # переключил мой флаг» от любого другого settings_changed: иначе
            # ручное включение при выключенном флажке гасилось бы сменой
            # чужого флага дома.
            event_context["_changed_role"] = setpoint_role

        payload = {
            "entity_id": entity_id,
            "new_state": new_state,
            "old_state": old_state,
            # Глобальные значения обязаны ехать с каждым событием, а не только
            # читаться при подключении: условия обогрева и охлаждения читают
            # уставку и сезон именно отсюда. Без этого `_event_context()` был
            # написан, но не вызывался — уставка доезжала до Home Assistant и
            # терялась по дороге к решению: `may_heat` получал «данных нет» и
            # отказывал при любой температуре, то есть обогрев не включался ни
            # разу (боевой дефект 2026-10-11: уставка 30 °C не включила ни
            # одного обогревателя).
            "context": event_context,
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
                    # Именно контекст из payload, а не исходный: глобальные
                    # значения (уставка, сезон, потолок комфорта) добавлены
                    # выше, и без них условие обогрева получало «данных нет»
                    # при любой температуре — обогрев не включался ни разу
                    # (боевой дефект 2026-10-11).
                    context=event_context,
                )
            except Exception as e:
                log.error(f"HAAdapter: EventRouter.route_state_change failed for {entity_id}: {e}")

        # Прибор вентиляции может сам снять назначенный режим: у боевого
        # рекуператора «Приток MAX» держится около пяти минут, и событие об
        # откате приходит как чужое изменение (`own_action` = False). Без этого
        # пересмотра откат замечал только сторож — раз в пять минут, и в бою
        # 2026-10-20 он прочитал состояние до отката и пропустил подтверждение:
        # спальня дула «Рекуперацией (лето)» на 100 % ещё пять минут.
        #
        # Эхо своей команды сюда не идёт намеренно: оно не сообщает ничего
        # нового, а лишний пересмотр мог бы отправить вторую команду и снова
        # зажечь дисплей рекуператора (B95).
        if not own_action and self._event_router is not None:
            route_device_change = getattr(self._event_router, "route_device_change", None)
            if route_device_change is not None:
                try:
                    await route_device_change(
                        entity_id=entity_id,
                        new_state=new_state,
                        old_state=old_state,
                        context=event_context,
                    )
                except Exception as e:
                    log.error(
                        f"HAAdapter: EventRouter.route_device_change failed for {entity_id}: {e}"
                    )

        # Ручное действие человека из Home Assistant: состояние меняет человек —
        # сам (`user_id`) или через свою кнопку и автоматизацию (`parent_id`).
        # Трекер это уже записал (из-за чего действует блокировка оверрайда), но
        # автомату нужно **событие**, чтобы войти в ручное состояние и потом
        # вернуться к автоматике через срок оверрайда (BACKLOG B57). Раньше такие
        # изменения до автомата не доходили: ручное состояние умел только UI-путь,
        # поэтому включённая руками гирлянда не возвращалась к автоматике.
        # Физический пульт шторы не оставляет user_id, но движение уже
        # опознано выше (`cover_movement`): автомат должен уйти в MANUAL, иначе
        # ручное положение не удержится до смены флагов дома (B104).
        # Физический выключатель света (`physical_manual`) и выключение розетки
        # обогревателя — тот же класс: событие должно дойти до автомата, чтобы
        # тот уступил человеку (B89, живая находка 2026-11-08).
        if human_action or cover_movement or physical_manual:
            await self._route_manual_event(entity_id, new_state, log)

        # Переключатели вентиляции (владелец, фиче-флаг, сезон, проветривание и
        # вытяжка) живут в Home Assistant и приходят не от датчика. Автомат
        # вентиляции ждёт показания температуры, поэтому без немедленного
        # пересмотра выключение вентиляции не действовало, пока датчик молчал
        # (боевой разбор 2026-10-12: рекуператор дул на 91 % при выключенном
        # выключателе владельца). Значение уже разобрано и лежит в контексте,
        # поэтому пересмотр видит его сразу. Признак «обогрев работает» считает
        # роутер — он один знает комнату и климат-автоматы.
        if (
            client is not None
            and self._is_settings_gate(entity_id)
            and self._event_router is not None
        ):
            try:
                await self._event_router.route_settings_change(event_context)
            except Exception as e:
                log.error(f"HAAdapter: пересмотр по смене настроек не удался: {e}")

    def _is_settings_gate(self, entity_id: str) -> bool:
        """Относится ли изменившаяся сущность к переключателям, которые
        пересматривают автоматы немедленно.

        Таких домена два: вентиляция (выключатель владельца, фиче-флаг, сезон,
        проветривание, вытяжка, а также числовые порог «жарко» и уставка) и
        шторы (фиче-флаг, «кто-то дома», «дома собаки», разрешение закрывать
        ночью, аварийный флаг). Плюс модификатор «мы спим» — он общий для света,
        вентиляции и штор, и его смена обязана дойти до автоматов, не дожидаясь
        датчика.

        Args:
            entity_id: Идентификатор изменившейся сущности.

        Returns:
            True, если смена этой сущности должна немедленно пересмотреть
            автоматы, которые слушают ``settings_changed``.
        """
        client = self._ws_client
        if client is None:
            return False
        sleep_entity = getattr(self, "sleep_modifier_entity", None)
        if sleep_entity and entity_id == sleep_entity:
            return True
        role_of = getattr(client, "global_role", None)
        if role_of is None:
            return False
        role = role_of(entity_id)
        return (
            role in _VENTILATION_RETRIGGER_ROLES
            or role in _COVER_RETRIGGER_ROLES
            or role in _LIGHTING_RETRIGGER_ROLES
        )

    async def _route_settings_change_if_possible(self) -> None:
        """Разослать ``settings_changed`` один раз при подключении.

        Нужно шторам: они не слушают датчики вовсе, поэтому без этого события
        решение не принималось бы до первого переключения флага дома, которого
        может не быть часами. Автоматы вентиляции событие уже понимают.

        Пересмотр помечается одноразовым признаком ``_startup_reapply`` только в первый раз —
        после запуска платформы: автомат восстановил прежнее состояние, но входа
        в него не было, поэтому восстановленный «Приток MAX» надо подтвердить как
        обычный вход, с включением прибора (боевая находка B43). При
        переподключении признак не ставится: прибор уже работает, а лишнее
        включение с процентом сбрасывает его режим (боевой разбор 2026-10-13).
        Признак видят только шаблоны вентиляции; у штор такого условия нет, и
        лишний ключ в контексте им не мешает.

        Returns:
            Ничего. Неудача не прерывает подключение — как и остальные чтения.
        """
        router = self._event_router
        if router is None:
            return
        startup = not self._startup_reapply_done
        try:
            await router.route_settings_change(
                {**self._event_context(), "_startup_reapply": startup}
            )
        except Exception as exc:  # noqa: BLE001 — сверка не должна ронять подключение
            logger.warning(f"HAAdapter: первый пересмотр настроек не удался: {exc}")
        self._startup_reapply_done = True

    async def helpers_command(self, command_type: str, **payload: Any) -> dict[str, Any]:
        """Отправить команду WebSocket API помощников Home Assistant (B79).

        Зеркало состояний автоматов создаёт вспомогательные элементы
        (`input_text`) через этот API: обычный ``call_service`` умеет только
        писать значения в уже существующие, а ручное создание двух десятков
        помощников — не работа для владельца.

        Args:
            command_type: Тип команды (``input_text/list``, ``input_text/create``).
            **payload: Поля команды.

        Returns:
            Ответ дома целиком: ``success`` и ``result`` либо ``error``.
        """
        client = self._ws_client
        sender = getattr(client, "command", None)
        if sender is None:
            return {
                "success": False,
                "error": {"code": "no_websocket", "message": "нет WebSocket-соединения"},
            }
        return await sender(command_type, **payload)

    async def get_entity_state(self, entity_id: str) -> str | None:
        """Прочитать состояние одной сущности через REST.

        Наружу, а не только для внутреннего чтения: наблюдение за батарейками
        (спека 014, FR-048) и сквозная проверка здоровья дома (F6) спрашивают
        состояние по имени, а не по событию.

        ``None`` здесь означает «значения нет» и **не говорит, почему**: сущности
        нет в доме или её не удалось прочитать. Различие называет
        ``_read_entity_state`` (К-5), и оно же уходит в журнал.

        Args:
            entity_id: Идентификатор сущности.

        Returns:
            Состояние как строка либо ``None``, если сущность не ответила.
        """
        state, _reason = await self._read_entity_state(entity_id)
        return state

    async def get_entity_snapshot(self, entity_id: str) -> dict[str, Any] | None:
        """Прочитать состояние и атрибуты одной сущности через REST.

        Нужно, чтобы не слать команду, когда прибор уже в нужном режиме: у
        боевого рекуператора от каждой команды вспыхивает дисплей (замечание
        владельца 2026-10-19), а повтор «того же режима» ничего не меняет.

        ``None`` означает «прочитать не удалось»: это не подтверждение того, что
        прибор уже в нужном состоянии, поэтому вызывающий обязан отправить
        команду.

        Args:
            entity_id: Идентификатор сущности.

        Returns:
            Словарь ``{"state": …, **атрибуты}`` либо ``None``.
        """
        client = self._ws_client
        session = self._session
        if client is None or session is None:
            return None
        base = cast(str, self._ws_url)
        base = base.replace("wss://", "https://").replace("ws://", "http://")
        url = f"{base.split('/api/websocket')[0].rstrip('/')}/api/states/{entity_id}"
        try:
            async with session.get(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    return None
                payload = await response.json()
        except Exception as exc:  # noqa: BLE001 — неизвестность не повод молчать
            logger.warning(f"Снимок {entity_id} не прочитан: {exc}")
            return None
        if not isinstance(payload, dict):
            return None
        snapshot: dict[str, Any] = {"state": payload.get("state")}
        attributes = payload.get("attributes")
        if isinstance(attributes, dict):
            snapshot.update(attributes)
        return snapshot

    async def find_dashboard(self, url_path: str) -> dict[str, Any] | None:
        """????? ?????? ?? ???? (?????????? ? adapters.home_assistant.dashboards)."""
        return await dashboards_api.find_dashboard(self._ws_client, url_path)

    async def create_dashboard(
        self, url_path: str, title: str, icon: str = "mdi:home-automation"
    ) -> bool:
        """??????? ?????? (?????????? ? adapters.home_assistant.dashboards)."""
        return await dashboards_api.create_dashboard(self._ws_client, url_path, title, icon)

    async def save_dashboard_config(self, url_path: str, config: dict[str, Any]) -> bool:
        """????????? ???????????? ?????? (?????????? ? dashboards)."""
        return await dashboards_api.save_dashboard_config(self._ws_client, url_path, config)

    async def get_dashboard_entities(self) -> set[str] | None:
        """???????? ?? ??????? (?????????? ? dashboards)."""
        return await dashboards_api.get_dashboard_entities(self._ws_client)

    async def _read_entity_state(self, entity: str) -> tuple[str | None, str]:
        """Прочитать состояние одной сущности через REST и назвать причину.

        Причины разделены намеренно (аудит 2026-10-16, К-5): «сущности нет в
        доме» (ответ 404) — дело оператора, «не прочитали» — временная беда,
        которую лечит повтор.

        Args:
            entity: Идентификатор сущности.

        Returns:
            Пару «состояние, причина»: ``READ_OK``, ``READ_ENTITY_ABSENT``,
            ``READ_FAILED`` либо ``READ_NO_CONNECTION``.
        """
        client = self._ws_client
        session = self._session
        if client is None or session is None:
            return None, READ_NO_CONNECTION
        base = cast(str, self._ws_url)
        base = base.replace("wss://", "https://").replace("ws://", "http://")
        url = f"{base.split('/api/websocket')[0].rstrip('/')}/api/states/{entity}"
        try:
            async with session.get(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status == 404:
                    self._report_absent_entity(entity)
                    return None, READ_ENTITY_ABSENT
                if response.status != 200:
                    logger.warning(
                        f"Глобальная сущность {entity} не прочитана: "
                        f"Home Assistant ответил {response.status}"
                    )
                    return None, READ_FAILED
                payload = await response.json()
        except Exception as exc:  # noqa: BLE001 — подключение важнее значения
            logger.warning(f"Глобальная сущность {entity} не прочитана: {exc}")
            return None, READ_FAILED

        state = payload.get("state") if isinstance(payload, dict) else None
        if entity.startswith("climate.") and isinstance(payload, dict):
            # Цель климат-устройства — в атрибуте temperature: состояние там
            # режим (heat/off), и читать его как уставку нельзя.
            attributes = payload.get("attributes")
            if isinstance(attributes, dict) and attributes.get("temperature") is not None:
                state = attributes.get("temperature")
        return (str(state) if state is not None else None), READ_OK

    def _report_absent_entity(self, entity: str) -> None:
        """Назвать отсутствующую в доме сущность — один раз на процесс.

        Args:
            entity: Идентификатор сущности.

        Returns:
            Ничего.
        """
        if entity in self._absent_reported:
            return
        self._absent_reported.add(entity)
        logger.warning(
            f"HAAdapter: сущность {entity} отсутствует в доме (Home Assistant "
            f"ответил 404) — манифест ссылается на неё, а дом её не отдаёт. "
            f"Это опечатка в манифесте или снятый прибор, а не сбой чтения."
        )

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
        await self._store_globals(self.climate_entities)

    async def _refresh_ventilation_globals(self) -> None:
        """Прочитать глобальные значения вентиляции при подключении.

        Право владельца выключить вентиляцию и режимы проветривания и вытяжки
        живут в Home Assistant. Не прочитав их при подключении, платформа до
        первого события считала бы, что вентиляция включена, а проветривания
        нет.

        Returns:
            Ничего.
        """
        await self._store_globals(self.ventilation_entities)

    async def _refresh_lighting_globals(self) -> None:
        """Прочитать глобальные значения света при подключении.

        Действие включения читает текущую цветовую температуру
        (``color_temp_current``), а служба света — границы «день/ночь». Без
        чтения при подключении лампа до первого события от этих сущностей
        включалась бы с прошлой температурой.

        Returns:
            Ничего.
        """
        await self._store_globals(self.lighting_entities)

    async def _refresh_cover_globals(self) -> None:
        """Прочитать флаги штор при подключении (спека 015).

        Шторы зависят только от флагов дома — «кто-то дома», «дома собаки»,
        разрешение закрывать ночью, аварийный флаг. Они живут в Home Assistant и
        не являются датчиками, поэтому без чтения при подключении штора до
        первого переключения флага не знала бы, закрываться ли ей.

        Returns:
            Ничего.
        """
        await self._store_globals(self.cover_entities)

    async def _store_globals(self, entities: dict[str, str]) -> None:
        """Прочитать глобальные сущности и записать их клиенту.

        Одна и та же работа была в трёх местах — климат, вентиляция, шторы.
        Собрана здесь, потому что различие причин чтения нужно в одном месте:
        отсутствующая сущность называется в журнале, а не выдаётся за «нет
        данных» (аудит 2026-10-16, К-5).

        Args:
            entities: Роль → сущность.

        Returns:
            Ничего.
        """
        client = self._ws_client
        if client is None:
            return
        for role, entity in entities.items():
            state, _reason = await self._read_entity_state(entity)
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

    def event_context(self, entity_id: str | None = None) -> dict[str, Any]:
        """Общий контекст события: солнце, «мы спим», глобальные значения.

        Открыто наружу: сторож вентиляции подтверждает решение тем же
        контекстом, что и события датчиков. Иначе подтверждение шло без уличной
        температуры и сезона, и условие «приток по погоде» отказывало
        `guard_data_missing` по 288 раз в сутки (B63).

        Args:
            entity_id: Сущность события; ``None`` — контекст без единиц таймера.

        Returns:
            Словарь контекста.
        """
        return self._event_context(entity_id)

    def _event_context(self, entity_id: str | None = None) -> dict[str, Any]:
        """Контекст события: солнце, сон, глобальные значения и единицы таймеров.

        Args:
            entity_id: Сущность, состояние которой изменилось. Нужна, чтобы
                приложить единицу измерения её таймера: у обогревателя своя
                единица, у света — никакой.

        Returns:
            Словарь контекста без привязки к конкретному событию.
        """
        client = self._ws_client
        return {
            "daylight": getattr(client, "daylight", None),
            "sleep_modifier_on": getattr(client, "asleep", None),
            **self._global_context(),
            **self._timer_unit_for(entity_id),
        }

    def _timer_unit_for(self, entity_id: str | None) -> dict[str, Any]:
        """Единица измерения таймера обогревателя, если событие — его.

        Без этого действие получало ``timer_unit = None`` и угадывало минуты для
        секундного таймера: обогреватель включался и гас через 15 секунд, а
        платформа показывала исправную работу (боевой дефект 2026-10-11).
        Единицы читаются один раз при подключении, поэтому и в контекст они
        попадают без обращения к сети.

        Args:
            entity_id: Сущность события.

        Returns:
            ``{"timer_unit": единица}`` либо пустой словарь.
        """
        if not entity_id:
            return {}
        timer = self.heater_timer_of.get(entity_id)
        if not timer:
            return {}
        unit = self._entity_units.get(timer)
        return {"timer_unit": unit} if unit else {}

    async def _reconcile_sensor_states(self) -> None:
        """Прочитать показания датчиков при подключении и разослать автоматам.

        Home Assistant присылает событие только при изменении, а текущих значений
        в момент подписки не отдаёт. Поэтому после перезапуска автомат живёт со
        значением, восстановленным из сохранённого состояния, и пока датчик
        молчит, решение принимается по устаревшему показанию: в бою 2026-10-12
        (B40) рекуператор спальни физически работал, а автомат считал ``IDLE``,
        потому что датчик не менялся больше часа.

        Сверка читает текущее состояние каждого датчика и проводит его тем же
        путём, что и настоящее событие (``route_state_change``), поэтому решения
        (и команды) принимаются по правде. Best-effort: недоступный датчик не
        должен мешать подключению.

        Returns:
            Ничего.
        """
        router = self._event_router
        if router is None:
            return
        for sensor_id in router.mapped_sensors():
            try:
                state, _reason = await self._read_entity_state(sensor_id)
                if state is None:
                    continue
                await router.route_state_change(
                    entity_id=sensor_id,
                    new_state=state,
                    old_state=state,
                    context=self._event_context(sensor_id),
                )
            except Exception as exc:  # noqa: BLE001 — сверка не должна ронять подключение
                logger.warning(f"HAAdapter: сверка датчика {sensor_id} не удалась: {exc}")

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
            client.lighting_entities = dict(self.lighting_entities)
            client.cover_entities = dict(self.cover_entities)
        await self._refresh_climate_globals()
        await self._refresh_ventilation_globals()
        await self._refresh_lighting_globals()
        await self._refresh_cover_globals()
        await self._reconcile_sensor_states()
        # Первый пересмотр штор: они не слушают датчики вовсе, а флаги дома могут
        # не меняться часами. Без этого события штора не приняла бы решение до
        # первого переключения флага. Пересмотр общий (settings_changed), поэтому
        # его получают и автоматы вентиляции — им он тоже не во вред.
        await self._route_settings_change_if_possible()

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
