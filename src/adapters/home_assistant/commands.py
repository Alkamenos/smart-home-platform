"""Command gateway for the Home Assistant adapter.

Extracted from HAAdapter (spec 018, US4): calling HA services, echo protection
and the platform-command window are one responsibility.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from adapters.ha_constants import (
    COMMAND_ECHO_WINDOW_SEC,
    DIVERGENCE_COMMAND_WINDOW_SEC,
)


logger = logging.getLogger(__name__)


class CommandGatewayMixin:
    """Call Home Assistant services and track own commands."""

    if TYPE_CHECKING:
        _deployment: Any
        _mode: str
        _hass: Any
        _ws_client: Any
        _own_context_ids: Any
        _recent_commands: dict[str, float]

        def _generate_trace_id(self) -> str: ...

        def _get_logger(self, trace_id: str) -> Any: ...

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str = "",
        data: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Вызвать сервис Home Assistant.

        Args:
            domain: Домен сервиса (``fan``, ``mqtt``).
            service: Имя сервиса (``turn_on``, ``publish``).
            entity_id: Сущность-адресат. Пусто — у сервиса адресата нет
                (``mqtt.publish`` публикует в топик, а не в сущность).
            data: Данные вызова.
            trace_id: Идентификатор трассы.

        Returns:
            True, если сервис выполнен.
        """
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

        # WARNING, а не INFO: логи адаптера наследуют корневой обработчик,
        # где info не виден (урок #70). На info выход в Home Assistant был
        # недоказуем — а именно здесь в бою 2026-10-11 и терялись команды
        # обогревателей: намерение принималось, а эта строка молчала, и цепочка
        # «решение → команда → прибор» выглядела исправной до конца.
        log.warning(
            f"HAAdapter: calling service {domain}.{service} for {entity_id or '(без сущности)'}, "
            f"data={data}"
        )

        try:
            if self._mode == "pyscript":
                ok = await self._call_service_pyscript(domain, service, entity_id, data, log)
            else:
                ok = await self._call_service_websocket(domain, service, entity_id, data, log)
        except Exception as e:
            log.error(f"HAAdapter: service call failed {domain}.{service} for {entity_id}: {e}")
            return False
        # Судьба команды пишется и при успехе: без этого «приняли намерение» и
        # «прибор выполнил» неразличимы, и утренний разбор не скажет, где оборвалась
        # цепочка «решение → команда → прибор».
        log.warning(
            f"HAAdapter: service {domain}.{service} for {entity_id}: "
            f"{'выполнен' if ok else 'НЕ выполнен'}"
        )
        return ok

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

        service_data = {**data}
        if entity_id:
            service_data["entity_id"] = entity_id

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

    def _remember_own_context(self, result: Any) -> bool:
        """Запомнить контекст только что отправленной команды.

        Args:
            result: Ответ Home Assistant на вызов сервиса.

        Returns:
            True, если контекст был и запомнен; False, если интеграция его не
            вернула (тогда изменение узнаётся по окну «мы командовали»).
        """
        if not isinstance(result, dict):
            return False
        context = result.get("context")
        if not isinstance(context, dict):
            return False
        context_id = context.get("id")
        if isinstance(context_id, str) and context_id:
            self._own_context_ids.append(context_id)
            return True
        return False

    def _is_own_context(self, context_id: Any) -> bool:
        """Событие вызвано нашей командой или пришло извне.

        Args:
            context_id: Идентификатор контекста из события Home Assistant.

        Returns:
            True, если событие порождено командой платформы.
        """
        return isinstance(context_id, str) and context_id in self._own_context_ids

    def _remember_command(self, entity_id: str) -> None:
        """Запомнить, что платформа только что командовала этому устройству.

        Нужно интеграциям, которые не несут `context.id` своей команды в
        изменении состояния: иначе платформа примет собственную команду за
        ручное действие и заблокирует себя (боевой разбор 2026-10-13).

        Args:
            entity_id: Сущность, которой отправлена команда.

        Returns:
            Ничего.
        """
        if not entity_id:
            return
        recent = getattr(self, "_recent_commands", None)
        if recent is None:
            recent = {}
            self._recent_commands = recent
        recent[entity_id] = time.monotonic()

    def was_commanded_recently(self, entity_id: str) -> bool:
        """Приказывали ли мы этому прибору недавно.

        Нужно сторожу сверки (BACKLOG B86): повторять решение стоит только тогда,
        когда приказ был **от нас** — расхождение значит «команда не дошла». Если
        приказа не было, прибор изменил кто-то другой, и повторять своё решение
        значит спорить с человеком.

        Окно шире, чем у защиты от эха собственной команды
        (`COMMAND_ECHO_WINDOW_SEC`): там речь о секундах вокруг команды, здесь — о
        цикле сторожа.

        Args:
            entity_id: Сущность прибора.

        Returns:
            True, если команда уходила не дольше
            ``DIVERGENCE_COMMAND_WINDOW_SEC`` назад.
        """
        moment = self._recent_commands.get(entity_id)
        if moment is None:
            return False
        return time.monotonic() - moment <= DIVERGENCE_COMMAND_WINDOW_SEC

    def _is_recent_command(self, entity_id: str) -> bool:
        """Командовали ли мы этому устройству только что.

        Args:
            entity_id: Сущность из события.

        Returns:
            True, если команда уходила не дольше COMMAND_ECHO_WINDOW_SEC назад.
        """
        recent = getattr(self, "_recent_commands", None)
        if not recent:
            return False
        at = recent.get(entity_id)
        if at is None:
            return False
        if time.monotonic() - at > COMMAND_ECHO_WINDOW_SEC:
            recent.pop(entity_id, None)
            return False
        return True

    async def create_persistent_notification(
        self, title: str, message: str, notification_id: str
    ) -> bool:
        """Создать или обновить persistent-уведомление в Home Assistant.

        Args:
            title: Заголовок.
            message: Текст.
            notification_id: Идентификатор уведомления (обновляется по нему).

        Returns:
            True, если Home Assistant принял вызов.
        """
        return await self.call_service(
            "persistent_notification",
            "create",
            "",
            {
                "title": title,
                "message": message,
                "notification_id": notification_id,
            },
        )

    async def dismiss_persistent_notification(self, notification_id: str) -> bool:
        """Снять persistent-уведомление.

        Args:
            notification_id: Идентификатор уведомления.

        Returns:
            True, если Home Assistant принял вызов.
        """
        return await self.call_service(
            "persistent_notification",
            "dismiss",
            "",
            {"notification_id": notification_id},
        )

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

        service_data = {**data}
        if entity_id:
            service_data["entity_id"] = entity_id

        # Окно «мы командовали» ставим ДО отправки: изменение состояния приходит
        # в цикл чтения, пока мы ещё ждём ответа сервиса, — и, отметив команду
        # после, мы опоздали бы (событие уже легло ручным действием, и платформа
        # заблокировала себя на 60 минут; боевой разбор 2026-10-13 с рекуператором
        # Vakio, который к тому же не несёт наш контекст в изменении).
        self._remember_command(entity_id)
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
