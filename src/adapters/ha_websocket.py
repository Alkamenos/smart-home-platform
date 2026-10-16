"""Транспорт WebSocket для Home Assistant (BACKLOG B80).

Вынесен из `ha_adapter.py`: это отдельная ответственность — соединение, подписка
на события и команды, — и она занимала почти треть файла. Адаптер поверх него
занимается домом: устройствами, контекстом, зеркалом.
"""

from __future__ import annotations

import asyncio
import contextlib
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
        # Смена модификатора в любую сторону — тому, кто решает по флагам дома
        # (шторы и вентиляция): свет получает отдельное `sleep_started` выше, но
        # ему эта новость не нужна дважды.
        if self._pending_sleep_changed:
            self._pending_sleep_changed = False
            notify_changed = self.on_sleep_changed
            if notify_changed is not None:
                try:
                    await notify_changed()
                except Exception as exc:  # noqa: BLE001 — отказ уведомления не роняет поток событий
                    logger.warning(f"HAAdapter: смена «мы спим» не донесена: {exc}")
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

            # Предел размера сообщения поднят намеренно. По умолчанию библиотека
            # рвёт сообщения больше мегабайта, а реестр сущностей дома весит
            # 1.23 МБ (2107 сущностей, замер 2026-10-16): ответ молча не доходил,
            # и чистка мусора считала, что все вспомогательные элементы «откуда
            # бог весть», вместо «описан в YAML» или «создан через интерфейс».
            # 16 МБ — не «без предела»: безграничное чтение дало бы одному
            # сообщению съесть память платформы.
            self.ws = await websockets.connect(self.url, max_size=16 * 1024 * 1024)
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


def _is_number(value: Any) -> bool:
    """Значение приводится к числу.

    Args:
        value: Что проверить.

    Returns:
        True, если это число или числовая строка.
    """
    try:
        float(value)  # type: ignore[arg-type]
        return True
    except (TypeError, ValueError):
        return False


def _as_float(value: Any) -> float | None:
    """Привести к числу или вернуть None.

    Args:
        value: Что привести.

    Returns:
        Число либо None.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
