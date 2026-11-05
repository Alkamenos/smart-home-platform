"""Watchdog checks (spec 018, T058).

Extracted from WatchdogService: collecting FSM states, reading device truth and
deciding whether an automaton is stuck are the check itself.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.fsm.engine import _diagnostic_context, _is_diagnostic_entity
from core.logger import get_logger
from services.watchdog_models import (
    DEVICE_OFF_STATES,
    DEVICE_ON_STATES,
    DEVICE_UNAVAILABLE_STATES,
    MISMATCH_CLIMATE_ON_DECISION_OFF,
    MISMATCH_DEVICE_OFF_DECISION_ON,
    MISMATCH_DEVICE_ON_DECISION_OFF,
    MISMATCH_DEVICE_UNAVAILABLE,
    MISMATCH_MANUAL_OVERRIDE,
    FsmSnapshot,
    FsmSnapshotEntry,
    _now_timestamp,
)


logger = get_logger(__name__)


def _device_mismatch_reason(expected: frozenset[str], actual: str | None) -> str | None:
    """Назвать расхождение «автомат ↔ прибор».

    Args:
        expected: Допустимые состояния прибора по решению автомата.
        actual: Фактическое состояние прибора; ``None`` — не прочитано.

    Returns:
        Вид расхождения либо ``None``, если прибор согласен с решением или
        ответа не было (молчание — не согласие, но и не приговор: его называют
        отдельным видом ``device_unavailable`` только по явному состоянию).
    """
    if actual is None:
        return None
    if actual in DEVICE_UNAVAILABLE_STATES:
        return MISMATCH_DEVICE_UNAVAILABLE
    if actual in expected:
        return None
    if actual in DEVICE_ON_STATES:
        return MISMATCH_DEVICE_ON_DECISION_OFF
    if actual in DEVICE_OFF_STATES:
        return MISMATCH_DEVICE_OFF_DECISION_ON
    return None


def _state_of(states: dict[str, dict[str, Any]], entity_id: str) -> str | None:
    """Состояние сущности из массового чтения.

    Args:
        states: Сущность → словарь состояния.
        entity_id: Сущность прибора.

    Returns:
        Состояние в нижнем регистре либо ``None``, если сущности нет в ответе.
    """
    item = states.get(entity_id)
    if item is None:
        return None
    value = item.get("state")
    if value is None:
        return None
    return str(value).strip().lower()


def _position_of(states: dict[str, dict[str, Any]], entity_id: str) -> int | None:
    """Положение шторы из массового чтения (``current_position``).

    Args:
        states: Сущность → словарь состояния.
        entity_id: Сущность прибора.

    Returns:
        Положение 0–100 либо ``None``, если прибор его не отдаёт.
    """
    item = states.get(entity_id) or {}
    attributes = item.get("attributes") or {}
    value = attributes.get("current_position")
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _group_members(states: dict[str, dict[str, Any]], devices: set[str]) -> dict[str, set[str]]:
    """Найти связи «группа → участники» среди известных приборов.

    Home Assistant отдаёт участников группы атрибутом ``entity_id`` (так у
    световых групп и групп вообще). Нужны только связи, затрагивающие приборы
    платформы: остальные к сверке отношения не имеют.

    Args:
        states: Сущность → словарь состояния из массового чтения.
        devices: Сущности приборов платформы.

    Returns:
        Группа → множество её участников (только те, что относятся к прибору).
    """
    members: dict[str, set[str]] = {}
    for entity_id, item in states.items():
        attributes = item.get("attributes") or {}
        listed = attributes.get("entity_id")
        if not isinstance(listed, list):
            continue
        children = {str(child) for child in listed if isinstance(child, str)}
        if children & devices:
            members[entity_id] = children
    return members


def _physical_family(device: str, members: dict[str, set[str]]) -> set[str]:
    """Семья физического прибора: он сам, его участники и его группы.

    Один физический прибор бывает описан дважды — группой и её лампой, — и
    решение прибора обязано собираться по всей семье, иначе автоматы «ссорятся»
    и гасят друг другу свет (живой случай 2026-10-14).

    Args:
        device: Сущность прибора.
        members: Связи «группа → участники».

    Returns:
        Множество сущностей семьи, включая сам прибор.
    """
    family = {device}
    family.update(members.get(device, set()))
    for group, children in members.items():
        if device in children:
            family.add(group)
            family.update(children)
    return family


#: Имена шаблонов климата в идентификаторе автомата.
#:
#: Идентификатор собирается как ``{устройство}_{шаблон}_{приоритет}``
#: (`core.fsm.naming`), и по нему видно, что автомат управляет обогревом.
#: Сторожу нужно это различать: у света «горит без решения» — уступка человеку,
#: у обогревателя — проблема.
CLIMATE_FSM_MARKERS = ("_climate_control_", "_climate_hysteresis_")


def _is_climate_fsm(entity_id: str) -> bool:
    """Управляет ли автомат климатом (обогревом или охлаждением).

    Args:
        entity_id: Идентификатор автомата.

    Returns:
        True, если в имени автомата есть шаблон климата.
    """
    return any(marker in entity_id for marker in CLIMATE_FSM_MARKERS)


def _agrees_with_device(own: frozenset[str] | None, aggregate: frozenset[str]) -> bool:
    """Совпадает ли решение автомата с итоговым решением прибора.

    У прибора бывает несколько автоматов, и повторять решение должен только тот,
    чьё решение итог и составило: иначе «ночник: выключено» гасил лампу, которую
    держит горящей основной свет.

    Args:
        own: Допустимые состояния прибора по решению этого автомата.
        aggregate: Итоговое решение прибора по всем его автоматам.

    Returns:
        True, если автомат согласен с итогом.
    """
    if own is None:
        return False
    return own == aggregate or bool(own & aggregate)


class WatchdogChecksMixin:
    """Build a snapshot of automata and device states."""

    _last_snapshot: FsmSnapshot | None

    async def check_once(self) -> FsmSnapshot:
        """Выполнить одну проверку и вернуть снимок.

        Returns:
            Снимок состояний. При сбое чтения состояний возвращается снимок с
            ``failed=True`` и пустым списком автоматов: сбой проверки не должен
            приводить к остановке проверок (FR-018).
        """
        try:
            entries = self._collect_entries()
        except Exception as exc:  # noqa: BLE001 - проверка обязана быть устойчивой
            logger.warning(f"Failed to collect FSM states: {type(exc).__name__}: {exc}")
            snapshot = FsmSnapshot(taken_at=_now_timestamp(), failed=True)
            self._last_snapshot = snapshot
            self._record_metrics(snapshot)
            return snapshot

        entries = await self._with_device_states(entries)
        await self._reassert_decisions(entries)
        snapshot = self._with_connection(entries)
        self._last_snapshot = snapshot
        self._record_metrics(snapshot)
        self._publish_problems(snapshot)
        logger.info(f"[WATCHDOG] {snapshot.to_json()}")
        self._log_diagnostics()
        return snapshot

    def _log_diagnostics(self) -> None:
        """Записать снимок входов климата и вентиляции.

        Раз в интервал в журнал уходит не только состояние автомата, но и
        контекст последнего решения: утренний разбор должен видеть ряд значений
        (улица, уставка, флаги, режим, скорость), даже если датчики молчали и
        событий не было. Без этого «ничего не происходило» неотличимо от
        «происходило, но вход был пуст».
        """
        explain = getattr(self.fsm_engine, "explain", None)
        for entity_id, state in self.fsm_engine.get_all_states().items():
            if not _is_diagnostic_entity(entity_id):
                continue
            reason = None
            if explain is not None:
                decision = explain(entity_id)
                reason = getattr(decision, "reason_code", None) if decision else None
            logger.info(
                f"[ДИАГНОСТИКА] {entity_id}: состояние {state.current_state}, "
                f"последнее решение {reason}, вход: "
                f"{_diagnostic_context(getattr(state, 'context', {}) or {})}"
            )

    def _collect_entries(self) -> tuple[FsmSnapshotEntry, ...]:
        """Собрать записи снимка по всем автоматам.

        Returns:
            Кортеж записей снимка.
        """
        now = self.clock()
        entries = []
        for entity_id, state in self.fsm_engine.get_all_states().items():
            expected = self.fsm_engine.expected_timeout_sec(entity_id)
            stuck = self._is_stuck(now, state.entered_at, expected)
            entries.append(
                FsmSnapshotEntry(
                    entity_id=entity_id,
                    device=self.fsm_engine.device_id_of(entity_id) or "",
                    state=state.current_state,
                    entered_at=state.entered_at,
                    last_transition=self.fsm_engine.get_last_transition_time(entity_id),
                    stuck=stuck,
                    expected_timeout_sec=expected,
                )
            )
        return tuple(entries)

    def _is_stuck(self, now: float, entered_at: float, expected_sec: float | None) -> bool:
        """Определить зависание по ожидаемому времени пребывания.

        Args:
            now: Текущее монотонное время.
            entered_at: Момент входа в состояние.
            expected_sec: Ожидаемое время пребывания; ``None`` — не проверять.

        Returns:
            True, если автомат застрял.
        """
        if expected_sec is None:
            return False
        return (now - entered_at) > expected_sec + self.settings.stuck_grace_sec

    async def _with_device_states(
        self, entries: tuple[FsmSnapshotEntry, ...]
    ) -> tuple[FsmSnapshotEntry, ...]:
        """Дополнить снимок фактическим состоянием приборов (концепция §7, п. 4).

        «Автомат ↔ прибор» — отдельное наблюдаемое состояние. Решение может быть
        «выключено», а прибор гореть: команда не применилась, прибор недоступен,
        кто-то включил свет мимо платформы. Без сверки такое расхождение невидимо,
        и утренний разбор не отличает «не мог» от «сделал». Сбой чтения — не
        расхождение: молчание внешней системы не повод объявлять отказ решения.

        Args:
            entries: Записи снимка по автоматам.

        Returns:
            Записи с фактическим состоянием прибора и названным расхождением.
        """
        reader = getattr(self.adapter, "get_entity_state", None)
        if reader is None:
            return entries

        # У прибора может быть несколько автоматов, и один физический прибор
        # бывает описан дважды: группа света и её единственная лампа — это один и
        # тот же прибор, и у каждого свой автомат. Поэтому решение прибора
        # собирается по **всей его семье** (сам прибор, его участники и группы, в
        # которые он входит): лампа должна гореть, если так решил хотя бы один
        # автомат семьи. Сверять автоматы по отдельности нельзя: «ночник:
        # выключено» или «участник группы: выключено» — не расхождение, и попытка
        # «починить» их гасила свет, который в ту же секунду зажигал автомат
        # группы (живой случай 2026-10-14: свет мигал).
        states = await self._read_all_states(reader)
        devices = {entry.device for entry in entries if entry.device}
        members = _group_members(states, devices)
        family = {device: _physical_family(device, members) for device in devices}

        own: dict[str, frozenset[str] | None] = {}
        intent: dict[str, set[str]] = {}
        for entry in entries:
            expected = self._expected_device_state(entry.entity_id, entry.state)
            own[entry.entity_id] = expected
            if expected is None or not entry.device:
                continue
            for relative in family.get(entry.device, {entry.device}):
                intent.setdefault(relative, set()).update(expected)

        expected_by_device: dict[str, frozenset[str]] = {}
        for device, values in intent.items():
            wanted_on = values & DEVICE_ON_STATES
            expected_by_device[device] = frozenset(wanted_on or values)

        enriched: list[FsmSnapshotEntry] = []
        for entry in entries:
            if not entry.device:
                enriched.append(entry)
                continue
            # Фактическое состояние читаем и тогда, когда решения нет (IDLE,
            # MANUAL): снимок должен показывать положение ручной шторы, даже
            # если автоматика намеренно её не сверяет.
            actual = _state_of(states, entry.device) if states else None
            if actual is None:
                actual = await self._read_device_state(reader, entry.device)
            position = _position_of(states, entry.device)
            moving = actual in {"opening", "closing"}
            if position is not None and not moving and str(entry.device or "").startswith("cover."):
                # Положение точнее ярлыка: 0 — закрыта, любое другое — открыта.
                actual = "closed" if position <= 0 else "open"
            expected = expected_by_device.get(entry.device)
            if expected is None:
                # Решения нет (ручная штора, IDLE): сверять нечего, но факт
                # прибора в снимке остаётся.
                enriched.append(
                    replace(
                        entry,
                        device_state=actual,
                        device_position=position,
                        device_moving=moving,
                    )
                )
                continue
            reason = _device_mismatch_reason(expected, actual)
            if moving:
                # Штора едет: итоговое положение ещё не наступило. Повтор
                # посреди хода дёргал бы мотор; дождёмся остановки.
                reason = None
            # Расхождение называет только тот автомат, чьё решение совпало с
            # итогом прибора: повторять решение «выключить» лампе, которую
            # решено держать горящей, нечего.
            if not _agrees_with_device(own.get(entry.entity_id), expected):
                reason = None
            if (
                reason is not None
                and reason != MISMATCH_DEVICE_UNAVAILABLE
                and self._manual_override_active(entry.device)
            ):
                # Человек вмешался: автоматика уступает по правилу оверрайда.
                # Это расхождение, но не отказ — прибора чинить нечего. Так
                # называется и «включено не нами», когда о вмешательстве известно
                # (правило владельца: уступка объяснима и временна).
                reason = MISMATCH_MANUAL_OVERRIDE
            if reason == MISMATCH_DEVICE_ON_DECISION_OFF and _is_climate_fsm(entry.entity_id):
                # У обогревателя «включён без решения» — не уступка, а проблема:
                # наш собственный отказ выключения выглядит точно так же, а цена
                # оставленного обогрева выше, чем у лампы. Ручное включение сюда
                # не попадает: выше оно уже названо `manual_override_active`.
                reason = MISMATCH_CLIMATE_ON_DECISION_OFF
            if reason is not None:
                logger.warning(
                    f"Расхождение «автомат ↔ прибор»: {entry.device} — автомат "
                    f"{entry.entity_id} в состоянии {entry.state}, прибор {actual!r} "
                    f"({reason})"
                )
            enriched.append(
                replace(
                    entry,
                    device_state=actual,
                    device_position=position,
                    device_moving=moving,
                    mismatch_reason=reason,
                )
            )
        return tuple(enriched)

    async def _read_all_states(self, reader: Any) -> dict[str, dict[str, Any]]:
        """Прочитать состояния всех сущностей одним запросом.

        Одним запросом — потому что за цикл сторож сверяет больше двадцати
        приборов, а состояния нужны ещё и для связей «группа ↔ участники»
        (атрибут ``entity_id`` группы). Если массового чтения нет (автономный
        режим, тесты), остаются поштучные запросы: без них сверка работает, но
        связей не видит.

        Args:
            reader: Читатель состояния одной сущности у адаптера.

        Returns:
            Сущность → словарь состояния (``state`` и ``attributes``).
        """
        del reader
        bulk = getattr(self.adapter, "get_all_states", None)
        if not callable(bulk):
            return {}
        try:
            raw = await bulk()
        except Exception as exc:  # noqa: BLE001 — сверка не должна ронять сторожа
            logger.warning(f"Сторож: состояния сущностей не прочитаны: {exc}")
            return {}
        states: dict[str, dict[str, Any]] = {}
        for item in raw or []:
            entity_id = item.get("entity_id")
            if isinstance(entity_id, str):
                states[entity_id] = item
        return states

    def _with_connection(self, entries: tuple[FsmSnapshotEntry, ...]) -> FsmSnapshot:
        """Дополнить снимок состоянием связи с внешней системой.

        В автономном режиме внешней системы нет, и её отсутствие проблемой не
        является (FR-014).

        Args:
            entries: Записи снимка.

        Returns:
            Итоговый снимок.
        """
        now = self.clock()
        checked, disconnected = self._check_connection(now)
        return FsmSnapshot(
            taken_at=_now_timestamp(),
            entries=entries,
            problem_count=sum(1 for entry in entries if entry.stuck or entry.mismatch_is_fault),
            ha_checked=checked,
            ha_disconnected=disconnected,
        )

    def _check_connection(self, now: float) -> tuple[bool, bool]:
        """Оценить связь с внешней системой.

        Args:
            now: Текущее монотонное время.

        Returns:
            Пара ``(проверялась ли связь, зафиксирована ли потеря)``.
        """
        if self.adapter is None:
            self._disconnected_since = None
            return False, False

        if self.adapter.is_connected:
            self._disconnected_since = None
            return True, False

        if self._disconnected_since is None:
            self._disconnected_since = now
            return True, False
        return True, (now - self._disconnected_since) >= self.settings.ha_loss_sec

    # Показатели и события
