"""Template loading and conversion for the FSM factory (spec 018, T059).

Extracted from FSMFactory: reading YAML templates, applying behavior params and
turning them into FSM definitions.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from core.definitions import YAMLFSMDefinition, YAMLTransition
from core.fsm.engine import FSMDefinition, Transition
from core.fsm.naming import fsm_entity_id
from core.models.manifest import BehaviorConfig


_PACKAGE_FEATURES_DIR = Path(__file__).resolve().parents[2] / "features"


#: Переопределение таймаута по имени действия перехода: у разных состояний
#: одного шаблона разные сроки, и параметр должен выбираться по переходу, а не
#: «первый подошедший». Ключ — имя действия, значение — имена параметров, по
#: порядку. Для действий, которых здесь нет, остаются общие ключи
#: (``motion_timeout_sec`` для света, ``airing_seconds`` для проветривания).
_TIMEOUT_OVERRIDE_KEYS: dict[str, tuple[str, ...]] = {
    "exhaust_after_timeout": ("exhaust_seconds",),
}


def _timeout_from_params(
    yaml_transition: YAMLTransition,
    params: dict | None,
    timeout_params_declared: bool = False,
) -> float | None:
    """Определяет таймаут перехода с учётом параметра поведения.

    ``timeout_sec`` в шаблоне — это значение по умолчанию, а не приговор: если
    пользователь задал в манифесте ``motion_timeout_sec``, он и должен действовать.
    Раньше параметр доходил до описания автомата и там оставался: таймаут всегда
    брался из YAML, то есть поле «задержка выключения» в манифесте было
    безмолвным обещанием (#71).

    Переопределяется только переход по триггеру ``timeout``: у остальных
    ``timeout_sec`` — это верхняя граница ожидания при входе в состояние, и
    подменять её пользовательским «задержкой выключения» неверно.

    Шаблон может сам назвать параметр у каждого настраиваемого таймаута
    (``timeout_param``). Тогда переходы без имени параметра закреплены: иначе
    общий ``motion_timeout_sec`` переписал бы и ручной таймер «мы спим» (B97),
    и срок возврата к автоматике. Шаблоны без такого объявления сохраняют
    прежнее правило «параметр выбирается по имени действия».

    Args:
        yaml_transition: Переход из шаблона.
        params: Параметры поведения из манифеста.
        timeout_params_declared: Шаблон называет параметры у своих таймаутов.

    Returns:
        Время ожидания перехода.
    """
    default = yaml_transition.timeout_sec
    if yaml_transition.trigger != "timeout" or not params:
        return default

    if timeout_params_declared:
        key = yaml_transition.timeout_param
        if not key:
            return default
        candidate = params.get(key)
        if (
            isinstance(candidate, (int, float))
            and not isinstance(candidate, bool)
            and candidate > 0
        ):
            return float(candidate)
        return default

    # Прежнее правило: параметр, которым поведение переопределяет таймер, зависит
    # от имени действия. У света это ``motion_timeout_sec``, у вентиляции —
    # ``airing_seconds`` (спека 014, FR-025), у вытяжки — ``exhaust_seconds``
    # (T085). Вытяжка объявлена отдельным именем действия: без этого
    # ``airing_seconds`` переопределял бы и таймер вытяжки, и полчаса
    # проветривания задавали бы срок снятия модификатора вытяжки.
    override_keys = _TIMEOUT_OVERRIDE_KEYS.get(
        yaml_transition.action or "", ("motion_timeout_sec", "airing_seconds")
    )
    override = None
    for key in override_keys:
        candidate = params.get(key)
        if (
            isinstance(candidate, (int, float))
            and not isinstance(candidate, bool)
            and candidate > 0
        ):
            override = candidate
            break
    if override is None:
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
    "scheduled_light": "lighting",
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
    # A7: диапазон уставки задан схемой шаблона (target_temp, 5–35), а не
    # манифестом. Второй набор setpoint_min/max не читался и только вводил
    # в заблуждение.
    "climate": (),
    "ventilation": ("manual_lockout_min", "airing_entity", "exhaust_entity"),
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


def _apply_domain_rules_to_behavior(
    behavior: Any,
    automation_rules: Any,
    time_zone: str | None = None,
) -> Any:
    """Перенести доменные значения в параметры поведения.

    Явный параметр устройства главнее доменного: иначе настройка, которую задал
    владелец в конкретной комнате, молча перетиралась бы общим значением дома.

    Args:
        behavior: Поведение из манифеста.
        automation_rules: Правила автоматизации дома.
        time_zone: Часовой пояс дома из метаданных экземпляра (B76/A9).

    Returns:
        Поведение с дополненными параметрами либо исходное без изменений.
    """
    domain = TEMPLATE_DOMAINS.get(behavior.template)
    domain_rules = _domain_rules_for_template(automation_rules, behavior.template)
    defaults: dict[str, Any] = {}
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


class FsmFactoryLoadingMixin:
    """Load templates and convert them to FSM definitions."""

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
        # Используем имя поведенческого шаблона (behavior.template), а не entity_id из YAML.
        # Правило живёт в `core.fsm.naming`: по нему же дашборд и зеркало находят
        # состояние автомата в Home Assistant.
        template_name = behavior_template_name if behavior_template_name else "fsm"
        new_entity_id = fsm_entity_id(device_id, template_name, behavior_priority)
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
        timeout_params_declared: bool = False,
    ) -> Transition:
        """
        Преобразовать YAMLTransition в Transition, резолвя строки в функции.

        Args:
            yaml_transition: Валидированная YAML-модель перехода.
            schedule_guard_fn: Опциональная функция guard для расписания.
            params: Параметры поведения из манифеста.
            timeout_params_declared: Шаблон называет параметры у своих таймаутов.

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
            timeout_sec=_timeout_from_params(yaml_transition, params, timeout_params_declared),
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
        # Шаблон объявляет параметры у своих таймаутов — значит, остальные
        # таймауты закреплены в нём и общим параметром не переписываются.
        timeout_params_declared = any(t.timeout_param for t in yaml_def.transitions)
        transitions = tuple(
            self._yaml_to_transition(t, schedule_guard_fn, yaml_def.params, timeout_params_declared)
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
        time_zone: str | None = None,
    ) -> BehaviorConfig:
        """Дописать в поведение правила дома, которых в нём нет.

        Окно тишины и список ночных комнат задаются один раз для всего дома —
        в ``automation_rules``; часовой пояс — в метаданных экземпляра. Условия
        читают их из параметров поведения, поэтому значения переносятся сюда,
        но **только отсутствующие**: явный параметр в конкретном устройстве
        всегда главнее.

        Args:
            behavior: Поведение из манифеста.
            automation_rules: Правила автоматизации дома.
            time_zone: Часовой пояс дома из ``instance`` (B76/A9).

        Returns:
            Новое поведение с дополненными параметрами.
        """
        domain = TEMPLATE_DOMAINS.get(behavior.template)
        domain_rules = _domain_rules_for_template(automation_rules, behavior.template)
        defaults: dict[str, Any] = {}
        if time_zone:
            defaults["time_zone"] = time_zone
        for name in _DOMAIN_RULE_NAMES.get(domain or "", ()):
            value = getattr(domain_rules, name, None) if domain_rules is not None else None
            if value is not None:
                defaults[name] = value
        if not defaults or all(key in behavior.params for key in defaults):
            return behavior
        return behavior.model_copy(update={"params": {**defaults, **behavior.params}})
