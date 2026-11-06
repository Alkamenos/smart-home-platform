"""Watchdog decision reassertion (spec 018, T058).

Extracted from WatchdogService: comparing an automaton decision with the device
and repeating our own command is a repair concern, separate from observation.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from typing import Any

from core.logger import get_logger
from services.watchdog_models import (
    ACTIVE_STATES,
    DEVICE_DIVERGED_TRIGGER,
    DEVICE_OFF_STATES,
    DEVICE_ON_STATES,
    DIVERGENCE_REASSERT_ATTEMPTS,
    IDLE_LIKE_STATES,
    MISMATCH_CLIMATE_ON_DECISION_OFF,
    MISMATCH_DEVICE_OFF_DECISION_ON,
    MISMATCH_DEVICE_ON_DECISION_OFF,
    MISMATCH_MANUAL_OVERRIDE,
    FsmSnapshotEntry,
)


logger = get_logger(__name__)


class WatchdogReassertMixin:
    """Repeat our own decisions when the device diverged from them."""

    async def _reassert_decisions(
        self, entries: tuple[FsmSnapshotEntry, ...], startup: bool = False
    ) -> None:
        """Повторить решение для приборов, разошедшихся с ним (B64).

        Сторож не выдумывает команду: он говорит автомату «прибор разошёлся с
        твоим решением», и автомат повторяет **своё** решение тем же действием,
        что и в обычном переходе. Так у света, штор и вентиляции остаётся один
        путь команды (посредник, блокировка человека, журнал), а не второй,
        собранный в сторожe.

        Повторы ограничены: прибор, который не отвечает (граница радиосвязи,
        недоступность), иначе получал бы команду каждый цикл.

        Args:
            entries: Записи снимка с фактическим состоянием приборов.
            startup: Первая проверка после запуска платформы. Лампу, которая
                горит после появления питания, гасим по решению автомата даже
                при ручной блокировке: питание — не действие человека.
        """
        trigger = getattr(self.fsm_engine, "trigger", None)
        if not callable(trigger):
            return
        for entry in entries:
            startup_light_cleanup = (
                startup
                and str(entry.device or "").startswith("light.")
                and entry.mismatch_reason == MISMATCH_DEVICE_ON_DECISION_OFF
            )
            if entry.device_moving:
                # Штора ещё едет: итоговое положение неизвестно, повтор
                # посреди хода только дёргал бы мотор.
                self._divergence_attempts.pop(entry.entity_id, None)
                continue
            if not entry.mismatch_is_fault and not startup_light_cleanup:
                # Прибор согласился или уступил человеку — счётчик повторов
                # начинается заново: следующий отказ снова получит повторы.
                self._divergence_attempts.pop(entry.entity_id, None)
                if (
                    str(entry.device or "").startswith("cover.")
                    and entry.mismatch_reason
                    in (MISMATCH_MANUAL_OVERRIDE, MISMATCH_DEVICE_ON_DECISION_OFF)
                    and not self._commanded_recently(entry.device)
                ):
                    # Штору открыли без нас: команду не повторяем, но модель
                    # обязана узнать правду, иначе останется в старом CLOSED.
                    await self._tell_device_truth(entry, trigger)
                continue
            if entry.mismatch_reason == MISMATCH_CLIMATE_ON_DECISION_OFF:
                # Тревога без повтора: человек мог включить обогреватель сам, а
                # `device_state_diverged` у климата не имеет перехода — повтор
                # стал бы отказом в журнале без единой команды прибору.
                self._divergence_attempts.pop(entry.entity_id, None)
                continue
            attempts = self._divergence_attempts.get(entry.entity_id, 0)
            if attempts >= DIVERGENCE_REASSERT_ATTEMPTS:
                continue
            if not startup_light_cleanup and not self._commanded_recently(entry.device):
                # Прибора мы не трогали — значит его изменил кто-то другой. Своё
                # решение не повторяем: спорить с человеком хуже, чем оставить
                # расхождение (в журнале оно названо, в тревогах видно). Но и
                # оставлять модель в неправде нельзя: автомату сообщается
                # настоящее состояние прибора, и шаблон света приводит модель в
                # соответствие (B89, боевой разбор 2026-10-17).
                logger.warning(
                    f"Повтор решения для {entry.device} пропущен: мы этому прибору "
                    f"не приказывали, а {entry.device_state!r} не совпало с "
                    f"автоматом {entry.entity_id} ({entry.mismatch_reason})"
                )
                await self._tell_device_truth(entry, trigger)
                continue
            if startup_light_cleanup:
                turn_off = getattr(self, "startup_light_off", None)
                if callable(turn_off):
                    try:
                        await turn_off(entry.device)
                    except Exception as exc:  # noqa: BLE001 — сверка не должна ронять сторож
                        logger.warning(
                            f"Стартовое выключение света {entry.device} не удалось: {exc}"
                        )
                    self._divergence_attempts[entry.entity_id] = attempts + 1
                    continue
            self._divergence_attempts[entry.entity_id] = attempts + 1
            logger.warning(
                f"Повтор решения для {entry.device}: прибор {entry.device_state!r} "
                f"не совпал с автоматом {entry.entity_id} ({entry.mismatch_reason}), "
                f"попытка {attempts + 1} из {DIVERGENCE_REASSERT_ATTEMPTS}"
            )
            try:
                context = {"bypass_lockout": True} if startup_light_cleanup else None
                await trigger(
                    entry.entity_id,
                    DEVICE_DIVERGED_TRIGGER,
                    context,
                    respect_debounce=False,
                )
            except Exception as exc:  # noqa: BLE001 — повтор не должен ронять проверку
                logger.warning(f"Повтор решения для {entry.entity_id} не удался: {exc}")

    async def _tell_device_truth(self, entry: FsmSnapshotEntry, trigger: Any) -> None:
        """Сказать автомату правду о приборе, когда команды от нас не было (B89).

        Прибор мог привести в нерабочее состояние кто-то вне платформы — человек
        выключателем или автоматизация Home Assistant. Ручное действие опознаётся по
        `user_id`, а у этих источников пользователя нет, поэтому платформа изменения
        не замечает и продолжает считать прибор работающим. Тогда решение в этом
        состоянии команду не шлёт (шаблон исходит из того, что делать нечего), а
        повтор запрещён — и расхождение остаётся навсегда: боевой разбор 2026-10-17
        в гостиной, свет не включался, пока по комнате ходили чаще, чем раз в
        10 минут.

        Признак одноразовый (``_device_is_off``): в накопленный контекст он не
        попадает и на следующем событии не всплывает (B43).

        Признак адресован **лампам и шторам**: у лампы «нерабочее» — это `off`, у
        шторы — `closed`, и словарь расхождений у них общий
        (``device_off_decision_on``): для обоих семейств шаблон сам решает, что
        значит факт. Вентиляция не здесь — у неё свой сторож, который и сообщает
        факт (B54).

        У шторы есть и обратная правда: она открыта, а решение — закрыть. Тогда
        отправляется ``_device_is_on``, и шаблон принимает фактическое `OPEN`.
        Ручное движение шторы тоже приводит модель к прибору, но только если мы
        сами ей не командовали: иначе это наша команда ещё в пути.

        Args:
            entry: Запись снимка с фактическим состоянием прибора.
            trigger: Вызов движка, принимающий (entity_id, событие, контекст).

        Returns:
            Ничего.
        """
        # Решение по виду расхождения, а не по сырому состоянию: «прибор не
        # работает» у каждого семейства своё, а вид один. Непрочитанный прибор сюда
        # не попадает вовсе — у него другой вид расхождения.
        device = str(entry.device or "")
        is_cover = device.startswith("cover.")
        if entry.mismatch_reason == MISMATCH_DEVICE_OFF_DECISION_ON:
            context = {"_device_is_off": True}
        elif entry.mismatch_reason == MISMATCH_DEVICE_ON_DECISION_OFF and is_cover:
            context = {"_device_is_on": True}
        elif entry.mismatch_reason == MISMATCH_MANUAL_OVERRIDE and is_cover:
            if entry.device_state in DEVICE_OFF_STATES:
                context = {"_device_is_off": True}
            elif entry.device_state in DEVICE_ON_STATES:
                context = {"_device_is_on": True}
            else:
                return
        else:
            return
        if not device.startswith(("light.", "cover.")):
            return
        try:
            await trigger(
                entry.entity_id,
                DEVICE_DIVERGED_TRIGGER,
                context,
                respect_debounce=False,
            )
        except Exception as exc:  # noqa: BLE001 — признание правды не должно ронять проверку
            logger.warning(f"Сторож: правда о приборе {entry.device} не передана: {exc}")

    def _commanded_recently(self, device_id: str) -> bool:
        """Приказывали ли мы этому прибору недавно (BACKLOG B86).

        Args:
            device_id: Сущность прибора.

        Returns:
            True, если приказ был от нас; без источника — True: сторож обязан
            чинить неотвечающие приборы, а в бою источник всегда есть.
        """
        supplier = self.command_recency_supplier
        if supplier is None:
            return True
        try:
            return bool(supplier(device_id))
        except Exception as exc:  # noqa: BLE001 — наблюдатель не должен падать
            logger.warning(f"Проверка «мы командовали прибору» для {device_id} не удалась: {exc}")
            return True

    def _manual_override_active(self, device_id: str) -> bool:
        """Действует ли для прибора ручная блокировка.

        Args:
            device_id: Сущность прибора.

        Returns:
            True, если человек вмешался и срок оверрайда ещё не истёк; сбой
            проверки считается «нет» — выдумывать уступку нельзя.
        """
        supplier = self.manual_override_supplier
        if supplier is None:
            return False
        try:
            return bool(supplier(device_id))
        except Exception as exc:  # noqa: BLE001 — проверка не должна ронять сторожа
            logger.warning(f"Сторож: блокировка для {device_id} не проверена: {exc}")
            return False

    async def _read_device_state(self, reader: Any, entity_id: str) -> str | None:
        """Прочитать состояние прибора, не роняя проверку.

        Args:
            reader: Асинхронный читатель состояния у адаптера.
            entity_id: Сущность прибора.

        Returns:
            Состояние в нижнем регистре либо ``None``, если прибор не ответил.
        """
        try:
            value = await reader(entity_id)
        except Exception as exc:  # noqa: BLE001 — проверка обязана быть устойчивой
            logger.warning(f"Сторож: состояние прибора {entity_id} не прочитано: {exc}")
            return None
        if value is None:
            return None
        return str(value).strip().lower()

    def _expected_device_state(self, entity_id: str, state: str) -> frozenset[str] | None:
        """Каким должен быть прибор по решению автомата.

        Сначала спрашивается решение движка (``outcome`` — «on»/«off»): оно
        записано действием перехода, а не выведено из имени состояния. Если
        решения нет (переход без действия), состояние читается по имени:
        ``OFF``/``IDLE``/``CLOSED`` — «выключено», ``ON*`` и работа климата и
        вентиляции — «включено».

        Args:
            entity_id: Автомат.
            state: Текущее состояние автомата.

        Returns:
            Допустимые состояния прибора; ``None`` — сверять нечего (состояние
            неизвестно движку, и угадывать по нему нельзя).
        """
        device = self.fsm_engine.device_id_of(entity_id) or ""
        is_cover = device.split(".", 1)[0] == "cover"

        explain = getattr(self.fsm_engine, "explain", None)
        outcome: str | None = None
        if callable(explain):
            decision = explain(entity_id)
            outcome = getattr(decision, "outcome", None) if decision is not None else None

        if outcome == "off":
            device_on = False
        elif outcome == "on":
            device_on = True
        else:
            name = state.strip().upper()
            if name.startswith("OFF") or name in IDLE_LIKE_STATES:
                device_on = False
            elif name.startswith("ON") or name in ACTIVE_STATES:
                device_on = True
            else:
                return None

        if is_cover:
            return frozenset({"open"}) if device_on else frozenset({"closed"})
        return frozenset({"on"}) if device_on else frozenset({"off"})
