"""WebSocket transport for the Home Assistant adapter.

Extracted from HAAdapter (spec 018, US4): connection loop, reconnects,
subscription, heartbeat and shutdown are transport concerns, not device logic.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any, cast

import aiohttp

from adapters.ha_websocket import HAS_WS_LIBRARY, SimpleHAWebSocketClient


HomeAssistantWS = SimpleHAWebSocketClient


logger = logging.getLogger(__name__)


class ConnectionMixin:
    """WebSocket connection lifecycle and reconnect loop."""

    _ws_client: HomeAssistantWS | None
    _session: aiohttp.ClientSession | None
    _reconnect_task: asyncio.Task[None] | None
    _connected_once: bool

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
        ``app.container → ha_adapter → src.core``.

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

    async def _publish_connection_established(self) -> None:
        """Сообщить платформе, что связь есть (в том числе после обрыва).

        Подписка Home Assistant отдаёт только изменения: события, пропущенные во
        время обрыва, никто не повторит. Поэтому о подключении узнаёт веб-слой и
        приводит состояния устройств к источнику истины — иначе прибор,
        изменившийся во время обрыва, оставался бы в платформе старым до
        следующего изменения (B62).

        Returns:
            Ничего. Отсутствие шины — не ошибка (тесты, локальный запуск).
        """
        from core.events.fsm_events import EVENT_HA_CONNECTED

        bus = getattr(self._engine, "event_bus", None)
        if bus is None:
            return
        try:
            await bus.publish(EVENT_HA_CONNECTED, {"connected_once": self._connected_once})
        except Exception as exc:  # noqa: BLE001 — уведомление не важнее связи
            logger.warning(f"HAAdapter: событие подключения не опубликовано: {exc}")

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
        # Плюс пересмотр по флагам дома: шторы и вентиляция слушают
        # `settings_changed`, а не `sleep_started`.
        client.on_sleep_changed = self._on_sleep_changed
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

    async def _on_sleep_changed(self) -> None:
        """Пересмотреть автоматы по смене «мы спим» (боевой дефект 2026-10-16).

        Модификатор — общий флаг дома, но до сих пор его смену получал только
        свет (событие ``sleep_started``): шторы и вентиляция решают по смене
        флагов дома (``settings_changed``) и о модификаторе не узнавали вовсе.
        Боевой случай: 16 октября в полночь «мы спим» включился, свет погас, а
        шторы остались открытыми — их автомат не получил ни одного повода
        пересмотреть решение до утра.

        Returns:
            Ничего. Неудача пересмотра не роняет поток событий.
        """
        router = self._event_router
        if router is None:
            return
        try:
            await router.route_settings_change(self._event_context())
        except Exception as exc:  # noqa: BLE001 — пересмотр не должен ронять поток
            logger.warning(f"HAAdapter: пересмотр по смене «мы спим» не удался: {exc}")

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

                # Единицы измерения таймеров обогревателей читаются один раз при
                # подключении, а не в действии: решение принимается на каждом
                # показании датчика, и запрос в сеть из действия означал бы либо
                # лишнюю нагрузку, либо отказ обогрева при обрыве связи.
                #
                # Без этого обогрев выглядит исправным и не работает: таймер
                # измеряется в секундах, а платформа отправляет минуты — 15
                # секунд вместо получаса, при этом автомат честно отрабатывает
                # свой таймер, сторож пишет `ok`, метрики показывают работу
                # (боевой дефект 2026-10-11).
                if self.heater_timers:
                    # WARNING, а не INFO: логи адаптера наследуют корневой
                    # обработчик, где info не виден (урок #70 — на info эта
                    # проверка молчала бы и не доказала бы ничего). Плюс сам
                    # факт чтения единиц достоин внимания оператора: по нему
                    # видно, что обогрев считает длительность в тех же
                    # единицах, что и таймер прибора.
                    logger.warning(
                        f"HAAdapter: единицы измерения таймеров читаются для "
                        f"{len(self.heater_timers)} сущностей"
                    )
                    learned = await self.refresh_entity_units(self.heater_timers)
                    logger.warning(
                        f"HAAdapter: прочитаны единицы {learned} из "
                        f"{len(self.heater_timers)} таймеров обогревателей"
                    )
                else:
                    # Молчание опаснее ошибки: без единиц платформа угадывает
                    # минуты и отправляет их в секундный таймер.
                    logger.warning(
                        "HAAdapter: список таймеров обогревателей пуст — единицы "
                        "измерения не прочитаны, длительность работы уйдёт в "
                        "минутах. Проверь, что в манифесте у обогревателей "
                        "задан параметр heater_timer"
                    )

                # Освещённость нужна сразу при подключении: событие солнца придёт
                # только на восходе или закате.
                await self._refresh_daylight()

                reconnect_delay = 1.0
                self._mark_connection_established()
                logger.info("✅ HAAdapter: WebSocket ready, backoff reset (delay=1.0s)")
                # О подключении узнаёт веб-слой: состояния устройств могли
                # отстать, пока связи не было (B62).
                await self._publish_connection_established()

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

            # Указание пользователя лежит в конверте события, а не в его данных.
            # Раньше оно подставлялось заглушкой и терялось: без него платформа
            # не отличала «человек выключил свет» от «сработал сценарий», а
            # ручная блокировка не включалась ни одним путём. Именно поэтому
            # человек гасил свет, а автоматика включала его обратно.
            ha_context = message.get("context") or {}

            # Кто изменил состояние, видно только здесь, в конверте (BACKLOG
            # B91): `user_id` — действие из приложения, `parent_id` —
            # автоматизация, сценарий или скрипт, ни того ни другого — сам
            # прибор (настенный выключатель, кнопка). Logbook Home Assistant
            # этого не различает: наша команда несёт того же пользователя, что
            # и приложение, поэтому рядом печатается `own` — «вернулась наша
            # собственная команда».
            own_change = self._is_own_context(ha_context.get("id")) or self._is_recent_command(
                entity_id
            )

            # WARNING, а не INFO: логи адаптера наследуют корневой обработчик,
            # где INFO не виден (урок #70). Событие уже прошло фильтр (`_deliver`
            # зовёт обработчик только для сущностей манифеста), поэтому это
            # ровно тот поток, по которому утром восстанавливается хронология:
            # какая сущность изменилась, с какого значения и на какое. Без этого
            # «датчик молчал» и «событие потерялось» неразличимы.
            logger.warning(
                f"📡 HA STATE CHANGE: {entity_id}: '{old_state}' -> '{new_state}'"
                f" | user={ha_context.get('user_id') or '-'}"
                f" parent={ha_context.get('parent_id') or '-'}"
                f" ctx={ha_context.get('id') or '-'}"
                f" own={own_change}"
            )
            log.info(
                f"HAAdapter: WebSocket state_change for {entity_id}: '{old_state}' -> '{new_state}'"
            )

            await self.on_state_change(
                entity_id=entity_id,
                new_state=new_state,
                old_state=old_state,
                context={
                    "trace_id": trace_id,
                    "source": "websocket",
                    "user_id": ha_context.get("user_id"),
                    "ha_context_id": ha_context.get("id"),
                    # Родительский контекст: он есть у автоматизации, сценария и
                    # скрипта Home Assistant и отсутствует у действия прибора.
                    # Нужен, чтобы отличать «сработал сценарий» от «человек у
                    # настенного выключателя» (BACKLOG B91).
                    "ha_parent_id": ha_context.get("parent_id"),
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
