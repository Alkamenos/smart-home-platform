"""
FSM Factory - Фабрика для создания FSM на основе композиции поведений.

Этот модуль создает экземпляры FSM для каждого поведения устройства,
загружая YAML-шаблоны из features/ и применяя параметры из BehaviorConfig.
"""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any, Callable, Coroutine

import yaml
from loguru import logger

from .definitions import YAMLFSMDefinition, YAMLTransition
from .fsm import FSMDefinition, Transition, FSMEngine
from .registry import Registry
from .models.manifest import BehaviorConfig


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
        features_dir: str = "features",
        event_bus: Any | None = None,
    ) -> None:
        """
        Инициализировать фабрику.
        
        Args:
            engine: Экземпляр FSMEngine для регистрации автоматов.
            registry: Экземпляр Registry для получения guard/action функций.
            features_dir: Путь к папке с YAML шаблонами.
            event_bus: Опциональный EventBus для подписки на события сенсоров.
        """
        self._engine = engine
        self._registry = registry
        self._features_dir = Path(features_dir)
        self._template_cache: dict[str, dict[str, Any]] = {}
        self._event_bus = event_bus

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
        
        with open(yaml_path, 'r', encoding='utf-8') as f:
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
        behavior_template_name: str
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
        # Формат: {device_id}__{template_name}_{priority}
        # Используем имя поведенческого шаблона (behavior.template), а не entity_id из YAML
        template_name = behavior_template_name if behavior_template_name else 'fsm'
        new_entity_id = f"{device_id}__{template_name}_{behavior_priority}"
        template_data['entity_id'] = new_entity_id

        # Внедряем params из BehaviorConfig
        template_data['params'] = params

        # Сохраняем оригинальный device_id для роутинга событий
        template_data['target_device_id'] = device_id

        logger.info(f"Created FSM instance '{new_entity_id}' for device '{device_id}' (priority={behavior_priority}, params={params})")

        return template_data

    def _yaml_to_transition(self, yaml_transition: YAMLTransition) -> Transition:
        """
        Преобразовать YAMLTransition в Transition, резолвя строки в функции.
        
        Args:
            yaml_transition: Валидированная YAML-модель перехода.
            
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

        return Transition(
            from_state=yaml_transition.from_state,
            to_state=yaml_transition.to_state,
            trigger=yaml_transition.trigger,
            guard=guard_fn,
            action=action_fn,
            timeout_sec=yaml_transition.timeout_sec,
        )

    def _yaml_to_fsm_definition(self, yaml_def: YAMLFSMDefinition) -> FSMDefinition:
        """
        Преобразовать YAMLFSMDefinition в FSMDefinition.
        
        Args:
            yaml_def: Валидированная YAML-модель определения FSM.
            
        Returns:
            FSMDefinition: Объект определения FSM для двигателя.
        """
        transitions = tuple(
            self._yaml_to_transition(t) for t in yaml_def.transitions
        )
        
        return FSMDefinition(
            entity_id=yaml_def.entity_id,
            initial_state=yaml_def.initial_state,
            states=tuple(yaml_def.states),
            transitions=transitions,
            debounce_sec=yaml_def.debounce_sec,
            params=yaml_def.params,
            target_device_id=yaml_def.target_device_id,
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

    def create_from_behavior(
        self, 
        device_id: str, 
        behavior: BehaviorConfig
    ) -> list[FSMDefinition]:
        """
        Создать FSM из одного поведения.
        
        Args:
            device_id: ID устройства.
            behavior: Конфигурация поведения.
            
        Returns:
            list[FSMDefinition]: Список созданных определений FSM.
        """
        definitions = []
        
        try:
            # Загружаем шаблон
            template_data = self._load_template(behavior.template)
            
            # Применяем параметры
            modified_data = self._apply_params_to_template(
                template_data,
                behavior.params,
                device_id,
                behavior.priority,
                device_id,
                behavior.template
            )
            
            # Валидация через Pydantic
            yaml_def = YAMLFSMDefinition.model_validate(modified_data)
            
            # Проверка guard/action функций
            warnings = self._validate_guards_and_actions(yaml_def)
            for warning in warnings:
                logger.warning(warning)
            
            # Преобразование в FSMDefinition
            fsm_def = self._yaml_to_fsm_definition(yaml_def)
            definitions.append(fsm_def)
            
            logger.info(f"Loaded FSM for behavior '{behavior.template}' on device '{device_id}'")
            
            # Подписаться на события сенсоров из params, если есть event_bus
            if self._event_bus is not None and behavior.params:
                self._subscribe_to_sensor_events(
                    device_id,
                    fsm_def.entity_id,
                    behavior.params,
                    behavior.template
                )
            
        except FileNotFoundError as e:
            logger.error(str(e))
        except Exception as e:
            logger.error(f"Failed to create FSM from behavior '{behavior.template}' for device '{device_id}': {e}")
        
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
        all_definitions = []
        
        for device in manifest.devices:
            device_id = device.id
            
            if not device.behaviors:
                logger.warning(f"Device '{device_id}' has no behaviors defined")
                continue
            
            # Сортируем behaviors по приоритету (меньше = выше приоритет)
            sorted_behaviors = sorted(device.behaviors, key=lambda b: b.priority)
            
            logger.info(f"Processing device '{device_id}' with {len(sorted_behaviors)} behaviors")
            
            for behavior in sorted_behaviors:
                definitions = self.create_from_behavior(device_id, behavior)
                all_definitions.extend(definitions)
        
        logger.info(f"Created {len(all_definitions)} FSM definitions from manifest")
        return all_definitions

    def register_in_engine(self, definitions: list[FSMDefinition]) -> None:
        """
        Зарегистрировать определения FSM в двигателе.
        
        Args:
            definitions: Список определений FSM для регистрации.
        """
        for definition in definitions:
            self._engine.register_definition(definition)
        
        logger.info(f"Registered {len(definitions)} FSM definitions in engine")

    def create_and_register(self, manifest: Any) -> list[FSMDefinition]:
        """
        Создать FSM из манифеста и сразу зарегистрировать их в двигателе.
        
        Args:
            manifest: Валидированный объект Manifest.
            
        Returns:
            list[FSMDefinition]: Список всех созданных и зарегистрированных определений.
        """
        definitions = self.create_from_manifest(manifest)
        self.register_in_engine(definitions)
        return definitions
