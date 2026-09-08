"""
Loader - Загрузчик YAML-конфигураций автоматов.

Этот модуль читает YAML файлы из папки features/, валидирует их через Pydantic,
преобразует в объекты FSMDefinition и регистрирует в FSMEngine.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from .definitions import YAMLFSMDefinition, YAMLTransition
from .fsm import FSMDefinition, Transition, FSMEngine
from .registry import Registry


class Loader:
    """
    Загрузчик YAML-конфигураций автоматов.
    
    Читает YAML файлы из указанной папки, валидирует их через Pydantic,
    преобразует в объекты FSMDefinition и регистрирует в FSMEngine.
    
    Usage:
        engine = FSMEngine()
        registry = Registry()
        loader = Loader(engine, registry)
        
        # Зарегистрировать guard/action функции
        registry.register_guard("is_night_time", is_night_time_fn)
        registry.register_action("turn_on_light", turn_on_light_fn)
        
        # Загрузить YAML файлы из папки features/
        loader.load_from_directory("features/")
    """

    def __init__(self, engine: FSMEngine, registry: Registry, features_dir: str = "features") -> None:
        """
        Инициализировать загрузчик.
        
        Args:
            engine: Экземпляр FSMEngine для регистрации автоматов.
            registry: Экземпляр Registry для получения guard/action функций.
            features_dir: Путь к папке с YAML файлами.
        """
        self._engine = engine
        self._registry = registry
        self._features_dir = Path(features_dir)

    def _yaml_to_transition(self, yaml_transition: YAMLTransition) -> Transition:
        """
        Преобразовать YAMLTransition в Transition, резолвя строки в функции.
        
        Args:
            yaml_transition: Валидированная YAML-модель перехода.
            
        Returns:
            Transition: Объект перехода для FSM с резолвленными функциями.
        """
        # Резолвим guard
        guard_fn = None
        if yaml_transition.guard:
            guard_fn = self._registry.get_guard(yaml_transition.guard)
            if guard_fn is None:
                logger.warning(f"Guard '{yaml_transition.guard}' not found in registry!")

        # Резолвим action
        action_fn = None
        if yaml_transition.action:
            action_fn = self._registry.get_action(yaml_transition.action)
            if action_fn is None:
                logger.warning(f"Action '{yaml_transition.action}' not found in registry!")

        return Transition(
            from_state=yaml_transition.from_state,
            to_state=yaml_transition.to_state,
            trigger=yaml_transition.trigger,
            guard=guard_fn,      # Теперь это Callable или None
            action=action_fn,    # Теперь это Callable или None
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

    def load_yaml_file(self, yaml_path: Path) -> list[FSMDefinition]:
        """
        Загрузить и обработать один YAML файл.
        
        Args:
            yaml_path: Путь к YAML файлу.
            
        Returns:
            list[FSMDefinition]: Список загруженных определений FSM.
        """
        definitions = []
        
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to read YAML file {yaml_path}: {e}")
            return definitions
        
        # YAML может содержать один автомат или список автоматов
        if not isinstance(data, list):
            data = [data]
        
        for item in data:
            try:
                # Валидация через Pydantic
                yaml_def = YAMLFSMDefinition.model_validate(item)
                
                # Проверка guard/action функций
                warnings = self._validate_guards_and_actions(yaml_def)
                for warning in warnings:
                    logger.warning(warning)
                
                # Преобразование в FSMDefinition
                fsm_def = self._yaml_to_fsm_definition(yaml_def)
                definitions.append(fsm_def)
                
                logger.info(f"Loaded FSM for entity '{fsm_def.entity_id}' from {yaml_path}")
                
            except Exception as e:
                logger.error(f"Failed to validate/load FSM from {yaml_path}: {e}")
        
        return definitions

    def load_from_directory(self, directory: str | None = None) -> list[FSMDefinition]:
        """
        Загрузить все YAML файлы из указанной директории.
        
        Args:
            directory: Путь к директории (по умолчанию используется features_dir).
            
        Returns:
            list[FSMDefinition]: Список всех загруженных определений FSM.
        """
        dir_path = Path(directory) if directory else self._features_dir
        
        if not dir_path.exists():
            logger.warning(f"Features directory does not exist: {dir_path}")
            return []
        
        all_definitions = []
        yaml_files = list(dir_path.glob("*.yaml")) + list(dir_path.glob("*.yml"))
        
        for yaml_file in yaml_files:
            definitions = self.load_yaml_file(yaml_file)
            all_definitions.extend(definitions)
        
        logger.info(f"Loaded {len(all_definitions)} FSM definitions from {dir_path}")
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

    def load_and_register(self, directory: str | None = None) -> list[FSMDefinition]:
        """
        Загрузить YAML файлы и сразу зарегистрировать их в двигателе.
        
        Args:
            directory: Путь к директории (по умолчанию используется features_dir).
            
        Returns:
            list[FSMDefinition]: Список всех загруженных и зарегистрированных определений.
        """
        # Загружаем и регистрируем FSM определения
        # guard/action функции уже резолвлены в _yaml_to_transition
        definitions = self.load_from_directory(directory)
        self.register_in_engine(definitions)
        return definitions

