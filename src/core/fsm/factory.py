"""
FSM Factory - Фабрика для создания FSM на основе композиции поведений.

Этот модуль создает экземпляры FSM для каждого поведения устройства,
загружая YAML-шаблоны из features/ и применяя параметры из BehaviorConfig.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from core.definitions import YAMLFSMDefinition, YAMLTransition
from core.fsm.engine import FSMDefinition, FSMEngine, Transition
from core.models.manifest import BehaviorConfig
from core.registry import Registry


class TemplateLoadError(Exception):
    """Шаблон поведения нельзя собрать.

    Отдельный тип нужен, чтобы отличить «опечатка в имени действия» от
    «сломан сам Python-код». Первое — ошибка владельца манифеста, и её надо
    показать с именем устройства; второе — дефект платформы, и его надо
    чинить, а не показывать как «устройство пропущено».
    """


class MissingTemplateError(TemplateLoadError, FileNotFoundError):
    """Шаблон поведения не найден в каталоге ``features/``.

    Наследует и ``TemplateLoadError`` (поведение не собрано — устройство
    пропускается, платформа работает), и ``FileNotFoundError``: отсутствие
    файла шаблона было и остаётся ошибкой о файле, о которой уже знают
    вызывающие (`tests/test_fsm_factory.py:162`).
    """


@dataclass(frozen=True)
class SkippedBehavior:
    """Поведение, которое не удалось собрать.

    Attributes:
        device_id: Устройство, ради которого поведение собиралось.
        template: Имя шаблона поведения.
        reason: Что именно не так, с именем опечатки.
    """

    device_id: str
    template: str
    reason: str


@dataclass
class LoadReport:
    """Что получилось и что не получилось при сборке манифеста.

    Нужен для устойчивой загрузки: решение владельца 2026-10-10 — «платформа
    должна быть максимально устойчивой, но при этом сообщать о любых
    проблемах». Устойчивость без отчёта — это молчаливая поломка, поэтому
    пропуски обязаны быть видны и в журнале, и в готовности.
    """

    loaded: int = 0
    """Сколько определений собрано."""

    skipped: list[SkippedBehavior] = field(default_factory=list)
    """Какие поведения не собраны и почему."""

    @property
    def ok(self) -> bool:
        """Нет ли пропусков.

        Returns:
            True, когда всё собралось.
        """
        return not self.skipped

    def as_dict(self) -> dict[str, Any]:
        """Сведения о загрузке для сводки готовности.

        Returns:
            Словарь со счётчиками и списком пропусков.
        """
        return {
            "loaded": self.loaded,
            "ok": self.ok,
            "skipped": [
                {"device_id": item.device_id, "template": item.template, "reason": item.reason}
                for item in self.skipped
            ],
        }


# Каталог с YAML-шаблонами автоматизаций: src/features/
_PACKAGE_FEATURES_DIR = Path(__file__).resolve().parents[2] / "features"


def _timeout_from_params(yaml_transition: YAMLTransition, params: dict | None) -> float | None:
    """Определяет таймаут перехода с учётом параметра поведения.

    ``timeout_sec`` в шаблоне — это значение по умолчанию, а не приговор: если
    пользователь задал в манифесте ``motion_timeout_sec``, он и должен действовать.
    Раньше параметр доходил до описания автомата и там оставался: таймаут всегда
    брался из YAML, то есть поле «задержка выключения» в манифесте было
    безмолвным обещанием (#71).

    Переопределяется только переход по триггеру ``timeout``: у остальных
    ``timeout_sec`` — это верхняя граница ожидания при входе в состояние, и
    подменять её пользовательским «задержкой выключения» неверно.

    Args:
        yaml_transition: Переход из шаблона.
        params: Параметры поведения из манифеста.

    Returns:
        Время ожидания перехода.
    """
    default = yaml_transition.timeout_sec
    if yaml_transition.trigger != "timeout" or not params:
        return default
    override = params.get("motion_timeout_sec")
    if isinstance(override, bool) or not isinstance(override, (int, float)) or override <= 0:
        return default
    return float(override)


#: Сопоставление «шаблон → домен правил». Ключ — имя шаблона поведения,
#: значение — имя секции в ``automation_rules``.
#:
#: Раньше здесь стояло ``getattr(automation_rules, behavior.template, None)``,
#: то есть сравнение строк. Имена совпадали только у освещения, а шаблоны
#: климата и вентиляции называются иначе, чем домены, поэтому ``getattr`` давал
#: ``None`` и доменные правила не применялись **никогда** — при этом манифест
#: загружался без единой ошибки (`research.md` D3).
TEMPLATE_DOMAINS: dict[str, str] = {
    "lighting": "lighting",
    "night_light": "lighting",
    "deco_light": "lighting",
    "climate_control": "climate",
    "humidity_ventilation": "ventilation",
    "ventilation_modes": "ventilation",
}

#: Значения доменных правил, переносимые в параметры поведения. Условия читают
#: их оттуда: движок раскладывает параметры поведения в контекст перехода
#: (``FSMEngine._definition_params``).
#:
#: Список разделён по доменам намеренно. Общий список означал бы, что границы
#: уставки климата попадают в параметры освещения — и наоборот: лишние поля в
#: параметрах поведения попадают в веб-интерфейс и в контракт, где их видно
#: как настройку, которой нет.
_DOMAIN_RULE_NAMES: dict[str, tuple[str, ...]] = {
    "lighting": (
        "quiet_from",
        "quiet_to",
        "night_motion_rooms",
        "always_on_motion_rooms",
    ),
    "climate": ("setpoint_min", "setpoint_max"),
    "ventilation": ("manual_lockout_min",),
}


def _domain_rules_for_template(automation_rules: Any, template_name: str) -> Any:
    """Правила домена, к которому относится шаблон.

    Args:
        automation_rules: Правила автоматизации дома.
        template_name: Имя шаблона поведения.

    Returns:
        Объект правил домена либо ``None``, если шаблон домену не принадлежит.
    """
    domain = TEMPLATE_DOMAINS.get(template_name)
    if domain is None:
        return None
    return getattr(automation_rules, domain, None)


def _apply_domain_rules_to_behavior(behavior: Any, automation_rules: Any) -> Any:
    """Перенести доменные значения в параметры поведения.

    Явный параметр устройства главнее доменного: иначе настройка, которую задал
    владелец в конкретной комнате, молча перетиралась бы общим значением дома.

    Args:
        behavior: Поведение из манифеста.
        automation_rules: Правила автоматизации дома.

    Returns:
        Поведение с дополненными параметрами либо исходное без изменений.
    """
    domain = TEMPLATE_DOMAINS.get(behavior.template)
    domain_rules = _domain_rules_for_template(automation_rules, behavior.template)
    defaults: dict[str, Any] = {}
    time_zone = getattr(automation_rules, "time_zone", None)
    if time_zone:
        defaults["time_zone"] = time_zone
    for name in _DOMAIN_RULE_NAMES.get(domain or "", ()):
        value = getattr(domain_rules, name, None) if domain_rules is not None else None
        if value is not None:
            defaults[name] = value
    if not defaults or all(key in behavior.params for key in defaults):
        return behavior
    return behavior.model_copy(update={"params": {**defaults, **behavior.params}})


def _resolve_features_dir(features_dir: str | None) -> Path:
    """Определить каталог с YAML-шаблонами автоматизаций.

    Путь по умолчанию вычисляется относительно пакета, а не относительно
    текущего рабочего каталога, иначе шаблоны не находились бы при запуске
    не из корня проекта.

    Args:
        features_dir: Явно заданный путь. Может быть относительным.

    Returns:
        Путь к каталогу с шаблонами.
    """
    if features_dir is None:
        return _PACKAGE_FEATURES_DIR

    candidate = Path(features_dir)
    if candidate.is_absolute() or candidate.is_dir():
        return candidate

    # Относительный путь не найден — пробуем разрешить его от корня проекта.
    project_relative = _PACKAGE_FEATURES_DIR.parent.parent / candidate
    if project_relative.is_dir():
        return project_relative

    logger.warning(
        f"Каталог шаблонов '{candidate}' не найден, используется {_PACKAGE_FEATURES_DIR}"
    )
    return _PACKAGE_FEATURES_DIR


class FSMFactory:
    """
    Фабрика для создания FSM на основе композиции поведений.

    Для каждого устройства итерация по device.behaviors:
    1. Находит соответствующий YAML-шаблон в features/
    2. Создает отдельный экземпляр FSM для каждого поведения
    3. Применяет параметры из params к шаблону
    4. Регистрирует все FSM в engine с уникальными entity_id

    Usage:
        engine = FSMEngine()
        registry = Registry()
        factory = FSMFactory(engine, registry)

        # Загрузить behaviors из манифеста
        manifest = load_manifest("instances/leonids_house/manifest.yaml")
        factory.create_from_manifest(manifest)
    """

    def __init__(
        self,
        engine: FSMEngine,
        registry: Registry,
        features_dir: str | None = None,
        event_bus: Any | None = None,
    ) -> None:
        """
        Инициализировать фабрику.

        Args:
            engine: Экземпляр FSMEngine для регистрации автоматов.
            registry: Экземпляр Registry для получения guard/action функций.
            features_dir: Путь к папке с YAML шаблонами. Если не указан,
                используется каталог ``features`` рядом с пакетом ``src``.
            event_bus: Опциональный EventBus для подписки на события сенсоров.
        """
        self._engine = engine
        self._registry = registry
        self._features_dir = _resolve_features_dir(features_dir)
        self._template_cache: dict[str, dict[str, Any]] = {}
        # Хранится как Any, а не Any | None: подписка на сенсоры в
        # create_from_manifest уже защищена проверкой `is not None`, но mypy
        # не сужает тип атрибута через границу метода. Аннотация ничего
        # не меняет во время выполнения.
        self._event_bus: Any = event_bus

    def _load_template(self, template_name: str) -> dict[str, Any]:
        """
        Загрузить YAML-шаблон из features/.

        Args:
            template_name: Имя шаблона (без расширения .yaml).

        Returns:
            dict: Данные шаблона.

        Raises:
            FileNotFoundError: Если шаблон не найден.
        """
        if template_name in self._template_cache:
            return copy.deepcopy(self._template_cache[template_name])

        yaml_path = self._features_dir / f"{template_name}.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError(f"Template '{template_name}' not found at {yaml_path}")

        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Кэшируем оригинал
        self._template_cache[template_name] = data
        return copy.deepcopy(data)

    def _apply_params_to_template(
        self,
        template_data: dict[str, Any],
        params: dict[str, Any],
        entity_id: str,
        behavior_priority: int,
        device_id: str,
        behavior_template_name: str,
    ) -> dict[str, Any]:
        """
        Применить параметры поведения к шаблону.

        Args:
            template_data: Данные шаблона.
            params: Параметры поведения из манифеста.
            entity_id: ID устройства.
            behavior_priority: Приоритет поведения.
            device_id: Оригинальный ID устройства для target_device_id.

        Returns:
            dict: Модифицированные данные шаблона с params и target_device_id.
        """
        # Переопределяем entity_id для уникальности FSM
        # Формат: {device_id}_{template_name}_{priority}
        # Используем имя поведенческого шаблона (behavior.template), а не entity_id из YAML
        template_name = behavior_template_name if behavior_template_name else "fsm"
        new_entity_id = f"{device_id}_{template_name}_{behavior_priority}"
        template_data["entity_id"] = new_entity_id

        # Внедряем params из BehaviorConfig
        template_data["params"] = params

        # Сохраняем оригинальный device_id для роутинга событий
        template_data["target_device_id"] = device_id

        logger.info(
            f"Created FSM instance '{new_entity_id}' for device '{device_id}' (priority={behavior_priority}, params={params})"
        )

        return template_data

    def _yaml_to_transition(
        self,
        yaml_transition: YAMLTransition,
        schedule_guard_fn=None,
        params: dict | None = None,
    ) -> Transition:
        """
        Преобразовать YAMLTransition в Transition, резолвя строки в функции.

        Args:
            yaml_transition: Валидированная YAML-модель перехода.
            schedule_guard_fn: Опциональная функция guard для расписания.
            params: Параметры поведения из манифеста.

        Returns:
            Transition: Объект перехода для FSM с резолвленными функциями.
        """
        guard_fn = None
        if yaml_transition.guard:
            guard_fn = self._registry.get_guard(yaml_transition.guard)
            if guard_fn is None:
                logger.warning(f"Guard '{yaml_transition.guard}' not found in registry!")

        action_fn = None
        if yaml_transition.action:
            action_fn = self._registry.get_action(yaml_transition.action)
            if action_fn is None:
                logger.warning(f"Action '{yaml_transition.action}' not found in registry!")

        # Если есть schedule_guard_fn, оборачиваем существующий guard или создаем новый
        if schedule_guard_fn is not None:
            original_guard = guard_fn
            if original_guard is not None:
                # Комбинируем оба guard: оба должны вернуть True
                def combined_guard(state, context):
                    return original_guard(state, context) and schedule_guard_fn(context)

                guard_fn = combined_guard
            else:

                def guard_fn(state, context):
                    return schedule_guard_fn(context)

        # Сохраняем исходное имя guard, чтобы визуализации не показывали
        # безликое "guard_fn" вместо meaningful имени из YAML-шаблона.
        if guard_fn is not None:
            parts = [name for name in (yaml_transition.guard, "schedule") if name]
            guard_fn.__name__ = "+".join(parts)

        return Transition(
            from_state=yaml_transition.from_state,
            to_state=yaml_transition.to_state,
            trigger=yaml_transition.trigger,
            guard=guard_fn,
            action=action_fn,
            timeout_sec=_timeout_from_params(yaml_transition, params),
        )

    def _yaml_to_fsm_definition(
        self, yaml_def: YAMLFSMDefinition, schedule_guard_fn=None
    ) -> FSMDefinition:
        """
        Преобразовать YAMLFSMDefinition в FSMDefinition.

        Args:
            yaml_def: Валидированная YAML-модель определения FSM.
            schedule_guard_fn: Опциональная функция guard для расписания.

        Returns:
            FSMDefinition: Объект определения FSM для двигателя.
        """
        transitions = tuple(
            self._yaml_to_transition(t, schedule_guard_fn, yaml_def.params)
            for t in yaml_def.transitions
        )

        return FSMDefinition(
            entity_id=yaml_def.entity_id,
            initial_state=yaml_def.initial_state,
            states=tuple(yaml_def.states),
            transitions=transitions,
            debounce_sec=yaml_def.debounce_sec,
            params=yaml_def.params,
            target_device_id=yaml_def.target_device_id,
            room=yaml_def.room,
        )

    def _validate_guards_and_actions(self, yaml_def: YAMLFSMDefinition) -> list[str]:
        """
        Проверить, что все guard и action функции зарегистрированы в реестре.

        Args:
            yaml_def: Валидированная YAML-модель определения FSM.

        Returns:
            list[str]: Список предупреждений о незарегистрированных функциях.
        """
        warnings = []

        for transition in yaml_def.transitions:
            if transition.guard and not self._registry.has_guard(transition.guard):
                warnings.append(
                    f"Guard '{transition.guard}' not found in registry for entity '{yaml_def.entity_id}'"
                )

            if transition.action and not self._registry.has_action(transition.action):
                warnings.append(
                    f"Action '{transition.action}' not found in registry for entity '{yaml_def.entity_id}'"
                )

        return warnings

    @staticmethod
    def _with_house_rules(
        behavior: BehaviorConfig,
        automation_rules: Any,
    ) -> BehaviorConfig:
        """Дописать в поведение правила дома, которых в нём нет.

        Окно тишины, список ночных комнат и часовой пояс задаются один раз для
        всего дома — в ``automation_rules``. Условия читают их из параметров
        поведения, поэтому значения переносятся сюда, но **только отсутствующие**:
        явный параметр в конкретном устройстве всегда главнее.

        Args:
            behavior: Поведение из манифеста.
            automation_rules: Правила автоматизации дома.

        Returns:
            Новое поведение с дополненными параметрами.
        """
        domain = TEMPLATE_DOMAINS.get(behavior.template)
        domain_rules = _domain_rules_for_template(automation_rules, behavior.template)
        defaults: dict[str, Any] = {}
        time_zone = getattr(automation_rules, "time_zone", None)
        if time_zone:
            defaults["time_zone"] = time_zone
        for name in _DOMAIN_RULE_NAMES.get(domain or "", ()):
            value = getattr(domain_rules, name, None) if domain_rules is not None else None
            if value is not None:
                defaults[name] = value
        if not defaults or all(key in behavior.params for key in defaults):
            return behavior
        return behavior.model_copy(update={"params": {**defaults, **behavior.params}})

    def create_from_behavior(
        self,
        device_id: str,
        behavior: BehaviorConfig,
        room_id: str | None = None,
    ) -> list[FSMDefinition]:
        """
        Создать FSM из одного поведения.

        Args:
            device_id: ID устройства.
            behavior: Конфигурация поведения.
            room_id: Комната устройства из манифеста. Нужна условиям, которые
                решают по-разному для разных комнат (ночью свет разрешён в
                санузле и запрещён в спальне).

        Returns:
            list[FSMDefinition]: Список созданных определений FSM.
        """
        definitions = []

        try:
            # Загружаем шаблон
            template_data = self._load_template(behavior.template)
            if room_id is not None:
                template_data["room"] = room_id

            # Применяем параметры
            modified_data = self._apply_params_to_template(
                template_data,
                behavior.params,
                device_id,
                behavior.priority,
                device_id,
                behavior.template,
            )

            # Валидация через Pydantic
            yaml_def = YAMLFSMDefinition.model_validate(modified_data)

            # Проверка guard/action функций. Раньше здесь был WARNING, и это
            # означало худший исход: опечатка в имени действия проходила
            # молча, `action_fn` оставался `None`, переход выполнялся вхолостую,
            # а дом выглядел исправным. Теперь это ошибка сборки — поведение
            # пропускается, а причина попадает в отчёт о загрузке
            # (`research.md` D8, решение владельца 2026-10-10).
            problems = self._validate_guards_and_actions(yaml_def)
            if problems:
                raise TemplateLoadError("; ".join(problems))

            # Если в params есть schedule, создаем guard функцию для проверки расписания
            schedule_guard_fn = None
            if behavior.params and "schedule" in behavior.params:
                from core.guards.schedule_guard import is_within_schedule

                schedule_guard_fn = is_within_schedule

            # Преобразование в FSMDefinition (с применением schedule guard если есть)
            fsm_def = self._yaml_to_fsm_definition(yaml_def, schedule_guard_fn)
            definitions.append(fsm_def)

            logger.info(f"Loaded FSM for behavior '{behavior.template}' on device '{device_id}'")

            # Подписаться на события сенсоров из params, если есть event_bus
            if self._event_bus is not None and behavior.params:
                self._subscribe_to_sensor_events(
                    device_id, fsm_def.entity_id, behavior.params, behavior.template
                )

        except TemplateLoadError:
            raise
        except FileNotFoundError as e:
            logger.error(str(e))
            raise MissingTemplateError(str(e)) from e
        except Exception as e:
            logger.error(
                f"Failed to create FSM from behavior '{behavior.template}' for device '{device_id}': {e}"
            )
            raise TemplateLoadError(str(e)) from e

        return definitions

    def _subscribe_to_sensor_events(
        self,
        device_id: str,
        fsm_entity_id: str,
        params: dict[str, Any],
        template_name: str,
    ) -> None:
        """
        Подписать FSM на события сенсоров из params.

        Для lighting и night_light шаблонов подписывает на motion_sensor events.

        Args:
            device_id: ID устройства.
            fsm_entity_id: entity_id созданной FSM.
            params: Параметры поведения (могут содержать motion_sensor).
            template_name: Имя шаблона (lighting, night_light, etc.).
        """
        # Извлекаем motion_sensor из params, если есть
        motion_sensor = params.get("motion_sensor")

        if motion_sensor:
            # Создаем handler для этой FSM
            async def motion_event_handler(
                event_type: str,
                payload: dict[str, Any],
                trace_id: str | None = None,
            ) -> None:
                """Обработчик событий motion sensor."""
                log = logger.bind(trace_id=trace_id or "unknown")

                # Определяем тип события по состоянию сенсора
                new_state = payload.get("new_state", "")
                if new_state == "on":
                    trigger_event = "motion_detected"
                elif new_state == "off":
                    trigger_event = "motion_cleared"
                else:
                    log.debug(f"Unknown state {new_state} for motion sensor {motion_sensor}")
                    return

                log.info(
                    f"FSMFactory: Motion event from {motion_sensor} -> "
                    f"triggering '{trigger_event}' for FSM '{fsm_entity_id}'"
                )

                # Триггерим событие в FSM
                try:
                    await self._engine.trigger(
                        entity_id=fsm_entity_id,
                        event=trigger_event,
                        external_ctx=payload,
                        trace_id=trace_id,
                    )
                except Exception as e:
                    log.error(f"Failed to trigger FSM '{fsm_entity_id}': {e}")

            # Подписываемся с фильтром по entity_id сенсора
            self._event_bus.subscribe_with_filter(
                event_type="state_change",
                filter_params={"entity_id": motion_sensor},
                handler=motion_event_handler,
            )

            logger.info(
                f"Subscribed FSM '{fsm_entity_id}' to motion sensor '{motion_sensor}' "
                f"(template: {template_name})"
            )

    def create_from_manifest(self, manifest: Any) -> list[FSMDefinition]:
        """
        Создать FSM для всех устройств из манифеста.

        Для каждого устройства итерируется по device.behaviors,
        загружается соответствующий YAML-шаблон и создается отдельная FSM.

        Args:
            manifest: Валидированный объект Manifest.

        Returns:
            list[FSMDefinition]: Список всех созданных определений FSM.
        """
        definitions, report = self.create_from_manifest_reported(manifest)
        return definitions

    def create_from_manifest_reported(
        self, manifest: Any
    ) -> tuple[list[FSMDefinition], LoadReport]:
        """Создать FSM и вернуть отчёт о том, что не получилось.

        Изоляция по устройству, а не по шаблону: два устройства в одной комнате
        могут пользоваться одним шаблоном, и поломка одного поведения не должна
        выключать соседнее. Решение владельца 2026-10-10: «платформа должна быть
        максимально устойчивой, но при этом сообщать о любых проблемах» —
        обе половины обязательны, поэтому пропуски собираются в отчёт, а не
        только пишутся в журнал.

        Args:
            manifest: Валидированный объект Manifest.

        Returns:
            Кортеж из собранных определений и отчёта о пропусках.
        """
        all_definitions: list[FSMDefinition] = []
        report = LoadReport()

        for room_id, device in manifest.all_devices:
            device_id = device.id

            if not device.behaviors:
                logger.warning(f"Device '{device_id}' has no behaviors defined")
                continue

            # Сортируем behaviors по приоритету (меньше = выше приоритет)
            sorted_behaviors = sorted(device.behaviors, key=lambda b: b.priority)

            logger.info(f"Processing device '{device_id}' with {len(sorted_behaviors)} behaviors")

            for behavior in sorted_behaviors:
                try:
                    definitions = self.create_from_behavior(
                        device_id,
                        self._with_house_rules(behavior, manifest.automation_rules),
                        room_id,
                    )
                except Exception as exc:  # noqa: BLE001 — одно устройство не должно ронять дом
                    reason = str(exc) or type(exc).__name__
                    report.skipped.append(
                        SkippedBehavior(
                            device_id=device_id,
                            template=behavior.template,
                            reason=reason,
                        )
                    )
                    logger.error(
                        f"Поведение '{behavior.template}' устройства '{device_id}' "
                        f"пропущено: {reason}"
                    )
                    continue
                all_definitions.extend(definitions)

        report.loaded = len(all_definitions)
        if report.skipped:
            logger.error(
                f"Из манифеста не собрано {len(report.skipped)} поведений, "
                f"работают {report.loaded}: {report.as_dict()['skipped']}"
            )
        logger.info(
            f"Created {len(all_definitions)} FSM definitions from manifest "
            f"({len(report.skipped)} skipped)"
        )
        return all_definitions, report

    def register_in_engine(self, definitions: list[FSMDefinition]) -> None:
        """
        Зарегистрировать определения FSM в двигателе.

        Args:
            definitions: Список определений FSM для регистрации.
        """
        for definition in definitions:
            self._engine.register_definition(definition)

        logger.info(f"Registered {len(definitions)} FSM definitions in engine")

    def create_and_register(
        self, manifest: Any, restore_states: bool = True
    ) -> list[FSMDefinition]:
        """
        Создать FSM из манифеста и сразу зарегистрировать их в двигателе.

        Args:
            manifest: Валидированный объект Manifest.
            restore_states: If True, attempt to restore saved states from persistence.
                           The FSM engine will check for persisted states and use them
                           instead of initial_state if valid saved states exist.

        Returns:
            list[FSMDefinition]: Список всех созданных и зарегистрированных определений.
        """
        definitions = self.create_from_manifest(manifest)

        # Register each definition with state restoration enabled
        for definition in definitions:
            self._engine.register_definition(definition, restore_state=restore_states)

        logger.info(f"Created and registered {len(definitions)} FSM definitions")
        return definitions
